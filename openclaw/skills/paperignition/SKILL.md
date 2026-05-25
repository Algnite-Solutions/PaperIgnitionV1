---
name: paperignition
version: 1.0.0
description: Search papers and read personalized daily digests from PaperIgnition (paperignition.com). Wraps the paperignition CLI for unified code path with Claude Code skill. Triggers on "search PaperIgnition for...", "find papers about...", "what's new in my digest?", "check today's recommendations", or any paper-discovery task.
---

# PaperIgnition (OpenClaw Skill)

PaperIgnition crawls arXiv daily and provides semantic paper search (`find_similar`) and personalized daily digests. This skill wraps the `paperignition` CLI — the same CLI used by the Claude Code skill — so both stay in sync automatically.

## Prerequisites

1. The `paperignition` CLI must be installed:
   - **Recommended**: `pipx install -e .` (works on macOS/Linux without PATH edits)
   - **Alternative**: `pip install -e .` inside an activated venv
   - **Note**: On macOS, `pip install -e .` with system Python places the script in `~/Library/Python/3.X/bin`, which is not on PATH by default. Use `pipx` or a venv.

## Configuration

Set the following environment variables before use. All can also be passed as CLI flags.

### Required (paper search + digest)

| Env var | Description | Example |
|---------|-------------|---------|
| `PI_API_KEY` | PaperIgnition API key (`pi_live_...`) | `pi_live_qYxFLS15TM...` |
| `PI_BASE_URL` | PaperIgnition backend URL | `https://www.paperignition.com` |

### Optional (Feishu delivery)

| Env var | Description | Used by |
|---------|-------------|---------|
| `FEISHU_APP_ID` | Feishu app ID | `skill.py feishu` |
| `FEISHU_APP_SECRET` | Feishu app secret | `skill.py feishu` |
| `FEISHU_OPEN_ID` | Recipient's Feishu open_id | `skill.py feishu` |

## Search Papers

### Semantic (vector) search — preferred for conceptual queries

```bash
paperignition --pretty search "graph neural networks for code optimization" --top-k 10
```

### BM25 (keyword) search — for precise term matching

```bash
paperignition --pretty search-bm25 "reinforcement learning human feedback" --top-k 5
```

## Daily Digest

### List today's recommendations

```bash
paperignition --pretty digest-list "Qi Zhu"
```

### Read a personalized blog summary

```bash
paperignition digest-blog <paper_id> "Qi Zhu"
```

## Feishu Delivery (OpenClaw-specific)

Send a message to Feishu. Requires `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_OPEN_ID` env vars.

```bash
./skill.py feishu "Daily digest: 3 new papers matching your focus areas"
```

## Workflows

### Workflow A: Brainstorming Search

1. Run `paperignition --pretty search "<query>" --top-k 10`
2. Read the results and synthesize: what themes emerge? what's surprising?
3. **Spark discussion**: for the top 2-3 papers, ask a provocative question linking the paper to current research
4. **Always mark clearly**: these are `find_similar` results — metadata only, no blog

### Workflow B: Daily Digest Review

1. Run `paperignition --pretty digest-list "Qi Zhu"` to get today's papers
2. Flag: papers that directly intersect with active research (RL, VLM, Agent)
3. Flag: papers that challenge assumptions or open new directions
4. Include PaperIgnition blog links for every digest paper
5. **Vibrant discussion**: pick the 2-3 most interesting and start a conversation
6. **Send to Feishu**: `./skill.py feishu "<concise summary>"` — top 3 papers with blog links, key provocations

## Output Handling

- Default output is JSON to stdout (agent-friendly).
- Use `--pretty` for indented JSON when displaying to the user.
- **Never invent paper IDs.** Always cite `doc_id` from search or digest results.
- **Digest papers**: include the PaperIgnition blog link (`https://www.paperignition.com/paper.html?id=...&username=...`)
- **Search results**: explicitly mark as `🔍 via find_similar` with metadata only (title, abstract, similarity)

## Discussion Principles

- **Don't dump paper lists.** Synthesize, connect, provoke.
- **Cross-reference** with active research threads (see `references/focus.md`)
- **Ask "what if"**: what if this finding applies to our problem?
- **Be opinionated**: flag papers that seem overhyped vs genuinely important
- **Track patterns**: if a theme recurs across digests, call it out

## Failure Modes

| Exit code | Meaning | Action |
|-----------|---------|--------|
| 2 | Missing API key | Ask user to set `PI_API_KEY` or run `paperignition configure` |
| 3 | Unauthorized (401) | Ask user to check/recreate their API key |
| 4 | Rate limited (429) | Wait `Retry-After` seconds and retry |
| 5 | Server error | Retry once after a short delay |

## Known Limitations

- Focus-area cross-referencing and composite briefings are deferred to a follow-up release. Currently, focus matching is done manually using `references/focus.md` as a reference guide.
- `references/focus.md` contains research focus areas for manual cross-referencing. A future CLI flag (`--focus`) will automate this.

## Reference Files

- `references/focus.md` — Current research focus areas for manual cross-referencing
- `skill.py` — Feishu delivery helper (OpenClaw-specific)
