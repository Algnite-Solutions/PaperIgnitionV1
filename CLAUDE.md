# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperIgnition v2 is a standalone AI-powered academic paper recommendation system. It fetches papers from arXiv, indexes them with pgvector for semantic search, generates blog summaries using Gemini LLMs, and delivers personalized recommendations. The system supports an H5 web frontend.

**Key difference from v1:** v2 is fully standalone — no external `AIgnite` package dependency. All needed functionality is inlined in the `core/` package.

### Architecture

```
PaperIgnitionV2/
├── core/                    # Shared library (replaces AIgnite)
│   ├── models.py            # DocSet, TextChunk, FigureChunk, TableChunk
│   ├── arxiv/               # arXiv extraction pipeline
│   │   ├── client.py        # ArxivClient: query API → metadata
│   │   ├── downloader.py    # PDF/image download with retry
│   │   ├── html_extractor.py# ar5iv HTML → chunks
│   │   └── pdf_extractor.py # PDF → markdown → chunks (VolcEngine OCR)
│   ├── generators.py        # GeminiBlogGenerator_default, _recommend
│   ├── rerankers.py         # GeminiReranker, GeminiRerankerPDF
│   └── prompts/             # YAML prompt templates
├── backend/                 # FastAPI service (port 8000)
│   ├── app/
│   │   ├── main.py          # App entry point with lifespan
│   │   ├── db_utils.py      # DatabaseManager, session dependencies
│   │   ├── routers/         # auth, users, papers, digests, favorites
│   │   ├── models/          # SQLAlchemy (users.py) + Pydantic (papers.py)
│   │   ├── auth/            # JWT auth (schemas.py, utils.py)
│   │   ├── crud/            # User CRUD operations
│   │   └── utils/           # index_utils (translation, search helpers)
│   ├── config_utils.py      # Unified config loader with .env support
│   └── configs/             # app_config.yaml, ci_config.yaml
├── orchestrator/            # Daily task automation
│   ├── orchestrator.py      # PaperIgnitionOrchestrator main class
│   ├── paper_pull.py        # PaperPullService (fetch + extract)
│   ├── generate_blog.py     # Blog generation wrappers
│   ├── api_clients.py       # BackendAPIClient (HTTP)
│   ├── storage_util.py      # LocalStorageManager, RDSDBManager, EmbeddingClient
│   ├── rate_limiter.py      # Thread-safe rate limiting + token tracking
│   ├── utils.py             # DocSet JSON serialization helpers
│   └── configs/             # development.yaml, production.yaml
├── beta_frontend/           # H5 web interface (HTML/JS + Nginx)
├── scripts/                 # init_all_tables.py, reset_password.py
└── tests/                   # unit/, integration/
```

### Database Architecture

Two PostgreSQL databases:

- **paperignition_user** (User DB) — users, research_domains, paper_recommendations, favorite_papers, user_retrieve_results, job_logs
- **paperignition** (Paper DB) — papers, text_chunks (GIN full-text index), paper_embeddings (pgvector HNSW)

Cloud services:
- **DashScope** — text-embedding-v4 (1536 dimensions) for query embeddings
- **Aliyun OSS** — PDF and image storage (bucket: `paperignition1`, prefix: `imgs/`)

### Configuration

Secrets live in `.env` files (never in YAML). YAML configs use `${VAR_NAME}` syntax for environment variable substitution.

- `backend/configs/app_config.yaml` — Production backend config
- `backend/configs/ci_config.yaml` — CI / local dev config (used by `PAPERIGNITION_LOCAL_MODE=true`)
- `orchestrator/configs/development.yaml` — Local orchestrator config
- `orchestrator/configs/production.yaml` — Production orchestrator config

Environment variables (see `.env.example`):
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME_PAPER`, `DB_NAME_USER`
- `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`
- `GEMINI_API_KEY`
- `OPENAI_BASE_URL`, `OPENAI_API_KEY` (DeepSeek)
- `ALIYUN_ACCESS_KEY_ID`, `ALIYUN_ACCESS_KEY_SECRET`, `ALIYUN_OSS_ENDPOINT`, `ALIYUN_OSS_BUCKET`
- `PAPERIGNITION_LOCAL_MODE` — set `true` to use ci_config.yaml
- `PAPERIGNITION_CONFIG` — override config path

## Development Commands

### Setup

```bash
# Install (editable mode)
pip install -e ".[dev]"

# Copy and fill in secrets
cp .env.example .env
```

### Database Initialization

```bash
# Create both databases (user + paper)
python scripts/init_all_tables.py

# User DB only
python scripts/init_all_tables.py --user-db-only

# Paper DB only
python scripts/init_all_tables.py --paper-db-only

# Drop and recreate
python scripts/init_all_tables.py --drop

# Local mode (uses ci_config.yaml)
PAPERIGNITION_LOCAL_MODE=true python scripts/init_all_tables.py
```

### Running Services

```bash
# Backend (port 8000)
uvicorn backend.app.main:app --reload --port 8000

# Frontend (Nginx, port 8080)
cd beta_frontend && nginx -c nginx_mac.conf   # macOS
```

### Running Tests

```bash
# Unit tests
pytest tests/unit/ -v

# Single test file
pytest tests/unit/test_models.py -v

# Single test function
pytest tests/unit/test_models.py::test_function_name -v

# Lint
ruff check .

# Lint with auto-fix
ruff check --fix .
```

**Note:** `asyncio_mode = "auto"` is set in pyproject.toml — async test functions are detected automatically without `@pytest.mark.asyncio`.

### Running Integration Tests (Local Docker)

Integration tests require PostgreSQL with pgvector. Use Docker to run them locally:

```bash
# Start postgres with pgvector
docker run -d --name pi-test-pg -p 5432:5432 \
  -e POSTGRES_USER=ci_user -e POSTGRES_PASSWORD=ci_password \
  pgvector/pgvector:pg16

# Initialize databases
python scripts/init_all_tables.py --config backend/configs/ci_config.yaml
# Run integration tests
pytest tests/integration/ -v

# Cleanup
docker stop pi-test-pg && docker rm pi-test-pg
```

Integration tests cover: auth, papers (pgvector similarity search), favorites, digests, orchestrator storage (RDSDBManager), domains, and health check. External APIs (DashScope) are mocked; the database is never mocked.

### Running Orchestrator

```bash
# Development (default config)
python orchestrator/orchestrator.py

# Production
python orchestrator/orchestrator.py configs/production.yaml

# Specific stages
python orchestrator/orchestrator.py --stages fetch_daily_papers generate_per_user_blogs

# Filter to specific users
python orchestrator/orchestrator.py --users "user@example.com" "demo@example.com"
```

### Utility Scripts

```bash
# Reset a user's password
python scripts/reset_password.py --username testuser --password newpass123

# Check for papers without blogs
bash scripts/check_empty_blogs.sh
```

## Code Architecture Details

### Core Package (`core/`)

Replaces the external AIgnite dependency. All imports use `from core.xxx`.

**DocSet model** (`core/models.py`): Papers are represented as `DocSet` objects with:
- Metadata: `doc_id`, `title`, `authors`, `abstract`, `categories`, `published_date`
- Content: `text_chunks`, `figure_chunks`, `table_chunks`
- Paths: `pdf_path`, `HTML_path`

**arXiv pipeline** (`core/arxiv/`): Three clear phases — query, download, extract:
1. `ArxivClient.fetch_papers()` — query arXiv API, return metadata-only DocSets
2. `downloader.download_pdf()` / `download_image()` — download with retry
3. `HTMLExtractor.extract()` or `PDFExtractor.extract()` — parse into chunks

### Backend Service (`backend/app/`)

FastAPI with async SQLAlchemy + asyncpg. Two database managers:
- `DatabaseManager` for user DB (via `get_db()` dependency)
- Paper DB manager (via `get_paper_db()` dependency)

**Key routers:**
- `papers.py` — pgvector semantic search (`/api/papers/find_similar`), paper content/metadata
- `digests.py` — user recommendations, blog content, feedback
- `auth.py` — email/password registration and login (JWT)
- `users.py` — profile management, interest translation
- `favorites.py` — favorite paper management

**Search flow** (`papers.py`):
1. DashScope API → query embedding (1536 dims)
2. SQL with pgvector: CTE pre-filter (date/exclusions) → cosine similarity → ranked results
3. When no filters: HNSW index for fast approximate search

**Compatibility routes** in `main.py`:
- `/find_similar/` → `/api/papers/find_similar`
- `/paper_content/{id}` → `/api/papers/content/{id}`
- `/get_metadata/{id}` → `/api/papers/metadata/{id}`

### Orchestrator (`orchestrator/`)

`PaperIgnitionOrchestrator` runs configurable stages:

1. **`fetch_daily_papers`** — fetch from arXiv → store to RDS → generate embeddings → upload images to OSS
2. **`generate_per_user_blogs`** — for each user: search → rerank (optional PDF-based) → generate personalized blogs → save recommendations

**Rate limiting**: Thread-safe per-model limits (RPM/RPD) configured in orchestrator YAML.

**Token tracking**: Automatic per-user token usage logging after API calls.

### API Endpoints

**Auth:**
- `POST /api/auth/register-email` — register with email/password
- `POST /api/auth/login-email` — login, returns JWT

**Papers:**
- `POST /api/papers/find_similar` — semantic search (pgvector)
- `GET /api/papers/content/{paper_id}` — global blog content
- `GET /api/papers/metadata/{doc_id}` — paper metadata

**Digests (user-specific):**
- `GET /api/digests/recommendations/{username}` — user's recommended papers
- `GET /api/digests/blog_content/{paper_id}/{username}` — personalized blog
- `POST /api/digests/recommend?username=X` — store recommendation

**Users:**
- `GET /api/users/me` — current user profile (requires JWT)
- `PUT /api/users/me/profile` — update profile
- `GET /api/users/all` — list all users

**Favorites:**
- `POST /api/favorites/add` — add favorite (requires JWT)
- `DELETE /api/favorites/remove/{paper_id}` — remove favorite
- `GET /api/favorites/list` — list favorites

**Other:**
- `GET /api/health` — health check
- `GET /api/domains` — list research domains

## Important Notes

- **No PYTHONPATH needed.** Install with `pip install -e .` and all packages (`core`, `backend`, `orchestrator`) are importable.
- **Embedding dimension is 1536** (DashScope text-embedding-v4). The backend `BackendEmbeddingClient` defaults to 2048 in the class but configs override to 1536.
- **PostgreSQL with pgvector** is required for the paper database. Run `CREATE EXTENSION IF NOT EXISTS vector` if needed.
- **Aliyun RDS** can be disabled (`aliyun_rds.enabled: false`) for local dev — paper search won't work but user auth will.
- Images are served from `http://oss.paperignition.com/imgs/` — markdown image paths are rewritten by the blog content endpoints.
- **Ruff config**: target Python 3.11, line length 120, selects E/F/I/W rules, ignores E501. Config is in `pyproject.toml`.
- **Requires Python ≥ 3.11.**
