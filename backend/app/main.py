import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db_utils import DatabaseManager, get_db, set_database_manager, set_paper_database_manager
from backend.app.limiter import limiter
from backend.app.models.users import ResearchDomain
from backend.app.routers import auth, digests, favorites, papers, users
from backend.config_utils import load_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = os.environ.get("PAPERIGNITION_CONFIG")
    if not config_path:
        local_mode = os.getenv("PAPERIGNITION_LOCAL_MODE", "false").lower() == "true"
        config_file = "ci_config.yaml" if local_mode else "app_config.yaml"
        config_path = os.path.join(os.path.dirname(__file__), "..", "configs", config_file)

    config = load_config(config_path)
    db_config = config.get("USER_DB", {})

    # Resolve security secrets from config into environment (so auth/utils.py can read them)
    security_config = config.get("security", {})
    if not os.environ.get("JWT_SECRET_KEY"):
        jwt_key = security_config.get("jwt_secret_key", "")
        if jwt_key:
            os.environ["JWT_SECRET_KEY"] = jwt_key
    if not os.environ.get("SERVICE_TOKEN"):
        svc_token = security_config.get("service_token", "")
        if svc_token:
            os.environ["SERVICE_TOKEN"] = svc_token

    # Update the module-level SECRET_KEY in auth/utils.py now that env is set.
    # NOTE: do NOT use `from ..auth.utils import SECRET_KEY` elsewhere — that
    # captures the pre-lifespan empty value. Always read via
    # `from ..auth import utils; utils.SECRET_KEY` or `os.environ["JWT_SECRET_KEY"]`.
    from backend.app.auth import utils as auth_utils
    auth_utils.SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "")

    # Startup validation: reject known-weak or missing secrets
    jwt_key = os.environ.get("JWT_SECRET_KEY", "")
    if not jwt_key or jwt_key in ("aignite_secret_key_change_in_production", ""):
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to a non-empty value.\n"
            "  For local dev: export PAPERIGNITION_LOCAL_MODE=true (loads ci_config.yaml)\n"
            "  For prod: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    local_mode = os.getenv("PAPERIGNITION_LOCAL_MODE", "false").lower() == "true"
    if not local_mode and jwt_key == "ci-test-secret-key":
        raise RuntimeError("JWT_SECRET_KEY must not be the CI test key in production")

    svc_token = os.environ.get("SERVICE_TOKEN", "")
    if not svc_token and not local_mode:
        import logging
        logging.getLogger(__name__).warning(
            "SERVICE_TOKEN not set — orchestrator-facing endpoints will reject all requests"
        )

    db_manager = DatabaseManager(db_config=db_config)
    await db_manager.initialize()
    set_database_manager(db_manager)

    aliyun_rds_config = config.get("aliyun_rds", {})
    if aliyun_rds_config.get("enabled", False):
        paper_db_config = {
            "db_user": aliyun_rds_config.get("db_user", "paperignition"),
            "db_password": aliyun_rds_config.get("db_password", ""),
            "db_host": aliyun_rds_config.get("db_host", "localhost"),
            "db_port": aliyun_rds_config.get("db_port", "5432"),
            "db_name": aliyun_rds_config.get("db_name_paper", "paperignition")
        }
        paper_db_manager = DatabaseManager(db_config=paper_db_config)
        await paper_db_manager.initialize()
        set_paper_database_manager(paper_db_manager)

    app.state.db_manager = db_manager
    app.state.config = config
    app.state.smtp_config = config.get("smtp", {"enabled": False})

    yield

    await db_manager.close()
    from backend.app.db_utils import get_paper_database_manager
    paper_db_mgr = get_paper_database_manager()
    if paper_db_mgr:
        await paper_db_mgr.close()


app = FastAPI(title="PaperIgnition API", lifespan=lifespan)

# Rate limiting — single shared Limiter instance
from slowapi import _rate_limit_exceeded_handler

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — explicit allow-list from env var, then YAML config, then dev-mode fallback
_cors_str = os.environ.get("CORS_ALLOW_ORIGINS", "")
if _cors_str:
    _cors_origins = [o.strip() for o in _cors_str.split(",") if o.strip()]
else:
    # Fall back to CORS config from YAML (loaded later at lifespan, but
    # middleware must be added before first request; env var is the primary source)
    _cors_origins = ["http://localhost:5173", "http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(papers.router, prefix="/api")
app.include_router(digests.router, prefix="/api")
app.include_router(favorites.router, prefix="/api")

# Compatibility routes
from backend.app.auth.utils import get_current_user  # noqa: E402 (after app creation to avoid circular import)
from backend.app.routers.papers import (
    FindSimilarRequest,
    FindSimilarResponse,
    find_similar_papers,
    get_paper_content,
    get_paper_db,
    get_paper_metadata,
)


@app.post("/find_similar/", response_model=FindSimilarResponse)
@limiter.limit("20/minute")
async def compat_find_similar(
    request_body: FindSimilarRequest,
    request: Request,
    db: AsyncSession = Depends(get_paper_db),
    current_user=Depends(get_current_user),
):
    return await find_similar_papers(request_body, request, db, current_user=current_user)


@app.get("/paper_content/{paper_id}")
async def compat_paper_content(paper_id: str, db: AsyncSession = Depends(get_paper_db)):
    return await get_paper_content(paper_id, db)


@app.get("/get_metadata/{doc_id}")
async def compat_get_metadata(doc_id: str, db: AsyncSession = Depends(get_paper_db)):
    return await get_paper_metadata(doc_id, db)


@app.get("/")
async def root():
    return {"message": "PaperIgnition API"}


@app.get("/api/domains")
async def get_research_domains(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(ResearchDomain))
    domains = result.scalars().all()
    return [{"id": d.id, "name": d.name, "code": d.code} for d in domains]


@app.get("/api/health")
async def health_check():
    import subprocess

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, timeout=5
        ).strip()
    except Exception:
        commit = "unknown"
    return {"status": "ok", "commit": commit}
