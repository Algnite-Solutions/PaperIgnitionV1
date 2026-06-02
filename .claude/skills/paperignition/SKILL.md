---
name: paperignition
version: 1.1.0
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

## Paragraph-Level Evidence Retrieval

After recalling candidate papers, do NOT extract fields from titles/abstracts. Use the chunk endpoints to locate specific paragraphs with `chunk_id` provenance.

### Search for relevant paragraphs across papers

```bash
paperignition --pretty search-chunks "GRPO reward model KL coefficient" --doc-ids 2401.12345 2402.67890 --top-k 20
```

Returns `{doc_id, chunk_id, chunk_order, snippet, score}` for each matching paragraph. The `--doc-ids` flag scopes the search to a recall set.

### Read all paragraphs of a paper (for surrounding context)

```bash
paperignition --pretty chunks <doc_id>
```

Returns `{doc_id, total, chunks: [{chunk_id, chunk_order, text_content}]}` ordered by position in the paper.

### Agent workflow for grounded extraction

1. **Recall** — `search` or `search-bm25` to find candidate papers
2. **Locate** — `search-chunks` to find paragraphs containing target keywords within the recalled set
3. **Read** — `chunks` for surrounding context around matches
4. **Extract** — every extracted field must cite a `chunk_id`

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
