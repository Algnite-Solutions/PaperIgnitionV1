---
name: paperignition
version: 1.0.0
description: Search PaperIgnition for similar papers (semantic + BM25) and read the user's daily digest / personalized blog. Trigger when the user asks to find related papers, brainstorm research ideas, or summarize today's digest.
---

# PaperIgnition Agent Skill

## Prerequisites

1. The `paperignition` CLI must be installed:
   - **Recommended**: `pipx install -e .` (works on macOS/Linux without PATH edits)
   - **Alternative**: `pip install -e .` inside an activated venv
   - **Note**: On macOS, `pip install -e .` with system Python places the script in `~/Library/Python/3.X/bin`, which is not on PATH by default. Use `pipx` or a venv.
2. An API key must exist and be configured:
   - Via env vars: `PI_API_KEY=pi_live_...` and `PI_BASE_URL=https://www.paperignition.com`
   - Or via `--api-key` / `--base-url` flags on each command

## Search Workflow

### Semantic (vector) search — preferred for conceptual queries

```bash
paperignition --pretty search "graph neural networks for code optimization" --top-k 10
```

### BM25 (keyword) search — for precise term matching

```bash
paperignition --pretty search-bm25 "reinforcement learning human feedback" --top-k 5
```

## Full Text Workflow

### Read a paper's OCR full text (from text_chunks)

```bash
paperignition full-text <doc_id>
```

Returns the raw concatenated markdown from the `text_chunks` table — the actual paper content, not the LLM blog summary. Use `content <paper_id>` only when you specifically want the blog.

## Digest Workflow

### List today's recommendations

```bash
paperignition --pretty digest-list <username>
```

### Read a personalized blog summary

```bash
paperignition digest-blog <paper_id> <username>
```

## Output Handling

- Default output is JSON to stdout (agent-friendly).
- Use `--pretty` for indented JSON when displaying to the user.
- **Never invent paper IDs.** Always cite `doc_id` from search or digest results.

## Failure Modes

| Exit code | Meaning | Action |
|-----------|---------|--------|
| 2 | Missing API key | Ask user to set `PI_API_KEY` or run `paperignition configure` |
| 3 | Unauthorized (401) | Ask user to check/recreate their API key |
| 4 | Rate limited (429) | Wait `Retry-After` seconds and retry |
| 5 | Server error | Retry once after a short delay |
