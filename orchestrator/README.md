# Orchestrator

The orchestrator automates the daily pipeline: fetch papers from arXiv, generate embeddings, recommend papers per user, extract content on demand, and generate personalized blog digests.

## Default Pipeline (Lazy Mode)

Lazy mode (`lazy_mode: true`) is the default in production. It optimizes for speed by deferring content extraction to only the papers that are actually recommended.

### Pipeline Stages

```
Stage 1: fetch_daily_papers
  arXiv API ──► metadata only (title, abstract, authors, categories)
       │
       ├──► Store metadata to Aliyun RDS (papers table)
       └──► Generate embeddings (DashScope text-embedding-v4, 1536 dims)
            └──► Store to RDS (paper_embeddings table, pgvector HNSW)

Stage 2: generate_per_user_blogs (for each user)
  User interests ──► pgvector similarity search (retrieve_k=20 candidates)
       │
       ├──► Rerank with Gemini (GeminiRerankerPDF or GeminiReranker)
       │    └──► Select top_k=5 papers
       │
       ├──► [Lazy] Extract content for top_k papers only
       │    ├──► ar5iv HTML extraction (primary)
       │    └──► PDF + VolcEngine OCR (fallback)
       │
       ├──► Generate personalized blog (Gemini)
       └──► Save recommendations to backend API
```

### Lazy vs Full Mode

| | Lazy Mode (default) | Full Mode |
|---|---|---|
| **Fetch** | Metadata only (~6s for 260 papers) | Metadata + content (~15min+) |
| **Content extraction** | Only for recommended papers (top_k per user) | All papers |
| **Image upload** | Only for recommended papers | All papers |
| **Config** | `lazy_mode: true` | `lazy_mode: false` |

### Why Lazy Mode?

On a typical day, arXiv publishes 200-400 CS papers. Each user only gets ~5 recommendations. Extracting content for all papers wastes time and API calls (VolcEngine OCR, ar5iv requests). Lazy mode reduces fetch time from 15+ minutes to under 10 seconds while still providing full content for the papers users actually read.

## Usage

```bash
# Source environment variables first
set -a && source .env && set +a

# Production (lazy mode, all users)
python orchestrator/orchestrator.py configs/production.yaml

# Single user
python orchestrator/orchestrator.py configs/production.yaml --users "Qi Zhu"

# Run specific stages only
python orchestrator/orchestrator.py configs/production.yaml --stages fetch_daily_papers
python orchestrator/orchestrator.py configs/production.yaml --stages generate_per_user_blogs

# Development config (local)
python orchestrator/orchestrator.py
```

## Configuration (`configs/production.yaml`)

### Paper Fetch

```yaml
paper_pull:
  max_workers: 8          # parallel arXiv API requests
  time_slots_count: 3     # split 24h into N slots to avoid API limits
  location: cloud         # "cloud" = UTC, or timezone like "Asia/Shanghai"
  count_delay: 2          # fetch papers from N days ago
  max_papers: null         # null = no limit
  lazy_mode: true          # metadata-only fetch; extract on demand
```

### User Recommendation

```yaml
user_recommendation:
  top_k: 5                # final recommendations per user
  retrieve_k: 20          # candidates from pgvector search
  similarity_cutoff: 0.1  # minimum cosine similarity
  search_days: 5           # search window
  customized_recommendation: true  # enable LLM reranking
  use_pdf_reranker: true   # use PDF-based reranker (downloads PDFs)
```

### Models

```yaml
models:
  blog_generation:
    model_id: gemini-3.1-flash-lite-preview
    rate_limits:
      rpm: 15
      rpd: 1500
  recommendation:
    model_id: gemini-3.1-flash-lite-preview
    rate_limits:
      rpm: 10
      rpd: 1000
```

### Deduplication

The orchestrator tracks processed paper IDs in `html_url_storage/html_urls.txt`. Papers already in this file are skipped on subsequent runs. Clear this file to re-process papers:

```bash
> orchestrator/html_url_storage/html_urls.txt
```

## Required Environment Variables

Set these in `.env` (sourced before running):

| Variable | Purpose |
|----------|---------|
| `APP_SERVICE_HOST` | Backend API URL (e.g. `http://localhost:8000`) |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME_PAPER` | Aliyun RDS PostgreSQL |
| `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL` | DashScope embedding API |
| `GEMINI_API_KEY` | Gemini LLM (blog generation + reranking) |
| `ALIYUN_ACCESS_KEY_ID`, `ALIYUN_ACCESS_KEY_SECRET` | OSS image upload |
| `VOLCENGINE_AK`, `VOLCENGINE_SK` | PDF OCR fallback (optional) |

## Content Extraction Pipeline

When a paper needs content extracted (all papers in full mode, only recommended papers in lazy mode):

1. **HTML extraction** (primary): Fetches from `ar5iv.labs.arxiv.org`, parses into text/figure/table chunks
2. **PDF fallback**: If HTML fails, downloads PDF from arXiv, uses VolcEngine OCR to convert to markdown, then extracts chunks
3. Extracted text chunks are stored to RDS (`text_chunks` table)
4. Figure images are uploaded to Aliyun OSS (`imgs/` prefix)
