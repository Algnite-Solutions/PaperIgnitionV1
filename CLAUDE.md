# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperIgnitionV1 is a standalone AI-powered academic paper recommendation system. It fetches papers from arXiv, indexes them with pgvector for semantic search, generates blog summaries using Gemini LLMs, and delivers personalized recommendations. The system supports an H5 web frontend.

**Key difference from PaperIgnition(Beta):** V1 is fully standalone — no external `AIgnite` package dependency. All needed functionality is inlined in the `core/` package.

### Architecture

```
PaperIgnitionV1/
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
- `ALIYUN_ACCESS_KEY_ID`, `ALIYUN_ACCESS_KEY_SECRET`, `ALIYUN_OSS_ENDPOINT`, `ALIYUN_OSS_BUCKET`
- `PAPERIGNITION_LOCAL_MODE` — set `true` to use ci_config.yaml
- `PAPERIGNITION_CONFIG` — override config path

## Deployment

### Backend (Aliyun — automated CD)

The backend runs on Aliyun at `120.55.55.116` behind nginx (HTTPS :443 → uvicorn :8000).

**CD flow** (`.github/workflows/cd.yml`, triggers after CI passes on `main`):
1. Rsyncs repo to `/root/PaperIgnitionV1/` on the Aliyun server
2. Runs `pip install -e .` to update dependencies
3. Copies nginx config and reloads nginx
4. Kills old uvicorn process and starts a new one on port 8000
5. Health check retries for up to 30s

**Secrets needed in GitHub repo settings:** `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`

### Orchestrator (Mac Mini — automated CD)

The orchestrator runs daily via Docker on a Mac Mini. CI builds and pushes the image; a cron job pulls and runs it.

**CI/CD flow:**
1. Push to `main` → CI runs lint + tests → `build-orchestrator` job builds multi-arch Docker image (amd64 + arm64)
2. Image pushed to `ghcr.io/algnite-solutions/paperignition-orchestrator:latest`
3. Mac Mini cron pulls `:latest` and runs it daily at 1am

**Docker image:** built from `Dockerfile.orchestrator`, CI config in `.github/workflows/ci.yml` (`build-orchestrator` job).

**First-time server setup:**

```bash
# 1. SSH into the Mac Mini
ssh leahai@leahs-mac-mini.lan

# 2. Ensure Docker is available (OrbStack or Docker Desktop)
docker --version

# 3. Create working directory and .env
mkdir -p ~/paperignition
cp .env.example ~/paperignition/.env   # fill in all secrets
# Key: APP_SERVICE_HOST=https://120.55.55.116

# 4. Authenticate with GHCR (GitHub Container Registry)
brew install gh                        # if not installed
gh auth login
gh auth refresh -h github.com -s read:packages,write:packages
gh auth token | docker login ghcr.io -u USERNAME --password-stdin

# 5. Pull and test the image
docker pull ghcr.io/algnite-solutions/paperignition-orchestrator:latest
docker run --rm --env-file ~/paperignition/.env \
  ghcr.io/algnite-solutions/paperignition-orchestrator:latest

# 6. Set up daily cron
crontab -e   # add the line below (runs at 1am local time daily):
# 0 1 * * * /usr/local/bin/docker pull ghcr.io/algnite-solutions/paperignition-orchestrator:latest >> /Users/leahai/paperignition/orchestrator.log 2>&1 && /usr/local/bin/docker run --rm --env-file /Users/leahai/paperignition/.env ghcr.io/algnite-solutions/paperignition-orchestrator:latest >> /Users/leahai/paperignition/orchestrator.log 2>&1
crontab -l   # verify
```

**Managing the cron:**
- `crontab -l` — list current schedule
- `crontab -e` — edit schedule (change time, disable, etc.)
- `crontab -r` — remove all cron jobs
- Logs: `tail -f ~/paperignition/orchestrator.log`

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

### Running Integration Tests

Integration tests require PostgreSQL with pgvector. You can use either Docker or local PostgreSQL.

#### Option 1: Local PostgreSQL

```bash
# Create test user and databases
sudo -u postgres psql -c "CREATE USER ci_user WITH PASSWORD 'ci_password' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE ci_user_db OWNER ci_user;"
sudo -u postgres psql -c "CREATE DATABASE ci_paper_db OWNER ci_user;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ci_user_db TO ci_user;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ci_paper_db TO ci_user;"

# Install pgvector extension (if not already installed)
sudo apt install -y build-essential git postgresql-server-dev-16
cd /tmp && git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git
cd pgvector && make PGCONFIG=/usr/lib/postgresql/16/bin/pg_config
sudo make install PGCONFIG=/usr/lib/postgresql/16/bin/pg_config
sudo -u postgres psql -d ci_paper_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Run integration tests
PAPERIGNITION_LOCAL_MODE=true pytest tests/integration/ -v
```

#### Option 2: Docker

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

**Test coverage:** auth, papers (pgvector similarity search + BM25 full-text search), favorites, digests, orchestrator storage (RDSDBManager), domains, and health check. External APIs (DashScope) are mocked; the database is never mocked.

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

*Semantic search (`/find_similar`)*:
1. DashScope API → query embedding (1536 dims)
2. SQL with pgvector: CTE pre-filter (date/exclusions) → cosine similarity → ranked results
3. When no filters: HNSW index for fast approximate search

*BM25 full-text search (`/find_similar_bm25`)*:
1. Query → PostgreSQL tsquery (AND logic for multiple terms)
2. SQL with fts_rank(): full-text search on title + abstract with weighted ranking
3. GIN index for fast text search
4. No external API calls required

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
- `POST /api/papers/find_similar` — semantic search (pgvector embeddings)
- `POST /api/papers/find_similar_bm25` — full-text search (BM25 / PostgreSQL ts_rank)
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
