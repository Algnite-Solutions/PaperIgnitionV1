import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db_utils import DatabaseManager, get_db, set_database_manager, set_paper_database_manager
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

    yield

    await db_manager.close()
    from backend.app.db_utils import get_paper_database_manager
    paper_db_mgr = get_paper_database_manager()
    if paper_db_mgr:
        await paper_db_mgr.close()


app = FastAPI(title="PaperIgnition API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
from fastapi import Request

from backend.app.routers.papers import (
    FindSimilarRequest,
    FindSimilarResponse,
    find_similar_papers,
    get_paper_content,
    get_paper_db,
    get_paper_metadata,
)


@app.post("/find_similar/", response_model=FindSimilarResponse)
async def compat_find_similar(request_body: FindSimilarRequest, request: Request, db: AsyncSession = Depends(get_paper_db)):
    return await find_similar_papers(request_body, request, db)


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
    return {"status": "ok"}
