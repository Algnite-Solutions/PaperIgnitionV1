"""
Shared test fixtures for integration tests.

Provides database initialization, FastAPI test client, user registration helpers,
and mock fixtures for external APIs (DashScope, etc.).
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Project root and CI config path
PROJECT_ROOT = Path(__file__).parent.parent.parent
CI_CONFIG_PATH = str(PROJECT_ROOT / "backend" / "configs" / "ci_config.yaml")


@pytest.fixture(scope="session")
def ci_config_path():
    return CI_CONFIG_PATH


@pytest.fixture(scope="session", autouse=True)
def init_databases(ci_config_path):
    """Initialize both user and paper databases once per test session."""
    os.environ["PAPERIGNITION_CONFIG"] = ci_config_path

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "init_all_tables.py"), "--config", ci_config_path, "--drop"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"Database init failed:\n{result.stderr}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def app_client(ci_config_path, init_databases):
    """Create FastAPI app with lifespan that persists for the whole test session."""
    os.environ["PAPERIGNITION_CONFIG"] = ci_config_path

    # Reset the global embedding client so it picks up CI config
    from backend.app.routers import papers

    papers._embedding_client = None
    papers._embedding_client_config = None

    from backend.app.main import app, lifespan

    async with lifespan(app):
        transport = ASGITransport(app=app)
        yield transport


@pytest_asyncio.fixture(loop_scope="session")
async def client(app_client):
    """Async HTTP client for each test."""
    async with AsyncClient(transport=app_client, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def clean_tables(ci_config_path):
    """Truncate mutable tables between tests (preserves schema + seed data)."""
    yield  # run test first

    from backend.config_utils import load_config

    config = load_config(ci_config_path)
    user_db = config["USER_DB"]
    rds = config["aliyun_rds"]

    # Clean user DB tables (preserve research_domains seed data)
    user_conn = psycopg2.connect(
        host=user_db["db_host"],
        port=user_db["db_port"],
        database=user_db["db_name"],
        user=user_db["db_user"],
        password=user_db["db_password"],
    )
    try:
        with user_conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE paper_recommendations, favorite_papers, "
                "user_retrieve_results, job_logs, user_domain_association, users CASCADE"
            )
        user_conn.commit()
    finally:
        user_conn.close()

    # Clean paper DB tables
    paper_conn = psycopg2.connect(
        host=rds["db_host"],
        port=rds["db_port"],
        database=rds["db_name_paper"],
        user=rds["db_user"],
        password=rds["db_password"],
    )
    try:
        with paper_conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE text_chunks, paper_embeddings, papers CASCADE")
        paper_conn.commit()
    finally:
        paper_conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def test_user(client):
    """Register a unique test user via the API, return credentials + JWT."""
    unique = uuid.uuid4().hex[:8]
    email = f"test_{unique}@example.com"
    username = f"testuser_{unique}"
    password = "TestPass123!"

    resp = await client.post(
        "/api/auth/register-email",
        json={"email": email, "password": password, "username": username},
    )
    assert resp.status_code == 200, f"Registration failed: {resp.text}"

    data = resp.json()
    return {
        "email": email,
        "username": username,
        "password": password,
        "access_token": data["access_token"],
    }


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers(test_user):
    """Return Authorization header dict for authenticated requests."""
    return {"Authorization": f"Bearer {test_user['access_token']}"}


@pytest.fixture
def mock_dashscope(monkeypatch):
    """Patch BackendEmbeddingClient.get_embedding to return a deterministic 1536-dim vector."""
    import math

    def fake_embedding(self, text):
        # Use a deterministic seed (not hash() which is randomized per-process)
        seed = sum(ord(c) for c in text) % (2**32)
        vec = []
        for i in range(1536):
            val = math.sin(seed + i) * 0.5
            vec.append(val)
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    from backend.app.routers.papers import BackendEmbeddingClient

    monkeypatch.setattr(BackendEmbeddingClient, "get_embedding", fake_embedding)


@pytest.fixture
def paper_db_conn(ci_config_path):
    """Direct psycopg2 connection to the paper database for seeding test data."""
    from backend.config_utils import load_config

    config = load_config(ci_config_path)
    rds = config["aliyun_rds"]

    conn = psycopg2.connect(
        host=rds["db_host"],
        port=rds["db_port"],
        database=rds["db_name_paper"],
        user=rds["db_user"],
        password=rds["db_password"],
    )
    yield conn
    conn.close()
