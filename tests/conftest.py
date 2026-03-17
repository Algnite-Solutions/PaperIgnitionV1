"""
Shared test fixtures for integration tests.

Provides database initialization, FastAPI test client, user registration helpers,
and mock fixtures for external APIs (DashScope, etc.).
"""

import os
import uuid
from pathlib import Path

import psycopg2
import pytest
from httpx import ASGITransport, AsyncClient

# CI config path
CI_CONFIG_PATH = str(Path(__file__).parent.parent / "backend" / "configs" / "ci_config.yaml")


@pytest.fixture(scope="session")
def ci_config_path():
    return CI_CONFIG_PATH


@pytest.fixture(scope="session", autouse=True)
def init_databases(ci_config_path):
    """Initialize both user and paper databases once per test session."""
    os.environ["PAPERIGNITION_CONFIG"] = ci_config_path

    from scripts.init_all_tables import init_paper_database, init_user_database

    init_user_database(ci_config_path, drop_existing=True)
    init_paper_database(ci_config_path, drop_existing=True)


@pytest.fixture(scope="session")
def app_client(ci_config_path, init_databases):
    """Create FastAPI app transport that persists for the whole test session."""
    os.environ["PAPERIGNITION_CONFIG"] = ci_config_path

    # Reset the global embedding client so it picks up CI config
    from backend.app.routers import papers

    papers._embedding_client = None
    papers._embedding_client_config = None

    from backend.app.main import app

    transport = ASGITransport(app=app)
    return transport, app


@pytest.fixture
async def client(app_client):
    """Async HTTP client for each test."""
    transport, _app = app_client
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
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


@pytest.fixture
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


@pytest.fixture
async def auth_headers(test_user):
    """Return Authorization header dict for authenticated requests."""
    return {"Authorization": f"Bearer {test_user['access_token']}"}


@pytest.fixture
def mock_dashscope(monkeypatch):
    """Patch BackendEmbeddingClient.get_embedding to return a deterministic 1536-dim vector."""
    import math

    def fake_embedding(self, text):
        h = hash(text) % (2**32)
        vec = []
        for i in range(1536):
            val = math.sin(h + i) * 0.5
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
