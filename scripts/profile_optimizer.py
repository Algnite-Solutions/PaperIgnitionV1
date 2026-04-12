"""
Standalone profile pool optimizer for interactive tuning.

Runs the same GEPA-style pool optimization as the orchestrator but outputs
results to console and local files — never writes to the database.

Usage:
    # Basic run (reads from prod DB, outputs to console)
    GEMINI_API_KEY=... python scripts/profile_optimizer.py --user "Qi Zhu"

    # Custom parameters
    python scripts/profile_optimizer.py --user "Qi Zhu" --max-papers 30 --max-val-days 5

    # Skip evaluation (extraction only, faster)
    python scripts/profile_optimizer.py --user "Qi Zhu" --no-eval

    # Use a specific model
    python scripts/profile_optimizer.py --user "Qi Zhu" --model gemini-3-flash-preview

    # Write results to file
    python scripts/profile_optimizer.py --user "Qi Zhu" --output results/qi_zhu_pool.json

    # Compare: also run single-profile extraction (old behavior) for comparison
    python scripts/profile_optimizer.py --user "Qi Zhu" --compare-single
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.arxiv.downloader import download_pdf
from core.profile_pool import PoolEvaluator, ProfilePoolOptimizer
from core.rerankers import GeminiProfileExtractor, GeminiRerankerPDF
from backend.config_utils import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_recommendations_from_db(username: str, config_path: str | None = None) -> list[dict]:
    """Fetch all recommendation records for a user directly from the DB."""
    import sqlalchemy
    from sqlalchemy import create_engine, text

    config = load_config(config_path)
    db_config = config.get("USER_DB", {})

    db_user = db_config.get("db_user", "postgres")
    db_password = db_config.get("db_password", "")
    db_host = db_config.get("db_host", "localhost")
    db_port = db_config.get("db_port", "5432")
    db_name = db_config.get("db_name", "paperignition_user")

    url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    engine = create_engine(url)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT paper_id, title, authors, abstract,
                   recommendation_date, blog_liked
            FROM paper_recommendations
            WHERE username = :username
            ORDER BY recommendation_date
        """), {"username": username}).fetchall()

    papers = []
    for r in rows:
        papers.append({
            "id": r[0],
            "title": r[1] or "",
            "authors": r[2] or "",
            "abstract": r[3] or "",
            "recommendation_date": r[4].isoformat() if r[4] else "",
            "blog_liked": r[5],
        })

    engine.dispose()
    return papers


def build_sessions(papers: list[dict]) -> tuple[list[dict], set[str]]:
    """Group papers into day sessions with labeled candidates."""
    sessions_raw: dict = defaultdict(list)
    for p in papers:
        rec_date = (p.get("recommendation_date") or "")[:10]
        if rec_date:
            sessions_raw[rec_date].append(p)

    all_sessions = []
    all_paper_ids: set = set()
    for day, day_papers in sorted(sessions_raw.items()):
        positives = [p for p in day_papers if p.get("blog_liked") is True]
        if not positives:
            continue
        negatives = [p for p in day_papers if p.get("blog_liked") is not True]
        candidates = []
        for p in positives:
            candidates.append({"paper_id": p["id"], "label": 1, "title": p.get("title", ""), "abstract": p.get("abstract", "")})
            all_paper_ids.add(p["id"])
        for p in negatives:
            candidates.append({"paper_id": p["id"], "label": 0, "title": p.get("title", ""), "abstract": p.get("abstract", "")})
            all_paper_ids.add(p["id"])
        all_sessions.append({"day": day, "candidates": candidates})

    return all_sessions, all_paper_ids


def download_pdfs(paper_ids: set[str], tmp_dir: Path) -> dict[str, str]:
    """Download PDFs from arXiv."""
    pdf_paths: dict = {}
    for paper_id in paper_ids:
        try:
            arxiv_id = paper_id.split("v")[0] if "v" in paper_id else paper_id
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
            path = download_pdf(pdf_url, tmp_dir, f"{arxiv_id}.pdf")
            if path:
                pdf_paths[paper_id] = str(path)
        except Exception as e:
            logging.warning(f"Failed to download PDF for {paper_id}: {e}")
    return pdf_paths


def print_profile(profile: dict, label: str = "Profile"):
    """Pretty-print a profile."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if not profile:
        print("  (empty/default)")
        return
    print(f"\n  Persona: {profile.get('persona_definition', 'N/A')}")
    print(f"\n  Ranking Heuristics:")
    for h in profile.get("ranking_heuristics", []):
        print(f"    - {h}")
    print(f"\n  Negative Constraints:")
    for c in profile.get("negative_constraints", []):
        print(f"    - {c}")
    if "changes_made" in profile:
        print(f"\n  Changes Made: {profile['changes_made']}")
    if "expected_improvement" in profile:
        print(f"  Expected Improvement: {profile['expected_improvement']}")
    print()


def print_pool_summary(pool: list[dict]):
    """Print a summary table of all pool candidates."""
    print(f"\n{'='*80}")
    print(f"  Pool Summary ({len(pool)} candidates)")
    print(f"{'='*80}")
    print(f"  {'#':<3} {'Gen':<4} {'Active':<7} {'Prec':<8} {'Recall':<8} {'F1':<8} {'ValDays':<8} Note")
    print(f"  {'-'*75}")
    for i, c in enumerate(pool):
        active = "***" if c.get("is_active") else ""
        prec = f"{c.get('precision_val', 0):.3f}" if c.get("precision_val") is not None else "N/A"
        recall = f"{c.get('recall_val', 0):.3f}" if c.get("recall_val") is not None else "N/A"
        f1 = f"{c.get('f1_val', 0):.3f}" if c.get("f1_val") is not None else "N/A"
        note = (c.get("mutation_note") or "")[:40]
        print(f"  {i:<3} {c.get('generation',0):<4} {active:<7} {prec:<8} {recall:<8} {f1:<8} {c.get('val_days_count',0):<8} {note}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Standalone profile pool optimizer (no DB writes)")
    parser.add_argument("--user", required=True, help="Username to optimize profile for")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini model (default: gemini-3-flash-preview)")
    parser.add_argument("--max-papers", type=int, default=50, help="Max papers for training (default: 50)")
    parser.add_argument("--max-val-days", type=int, default=7, help="Max validation days (default: 7)")
    parser.add_argument("--pool-size", type=int, default=5, help="Max pool size (default: 5)")
    parser.add_argument("--no-eval", action="store_true", help="Skip evaluation (extraction only)")
    parser.add_argument("--compare-single", action="store_true", help="Also run single-profile extraction for comparison")
    parser.add_argument("--output", type=str, default=None, help="Save results to JSON file")
    parser.add_argument("--config", type=str, default=None, help="Backend config path (for DB connection)")
    args = parser.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable required")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Profile Pool Optimizer — {args.user}")
    print(f"  Model: {args.model}")
    print(f"  Max papers: {args.max_papers}, Max val days: {args.max_val_days}")
    print(f"  Pool size: {args.pool_size}, Eval: {not args.no_eval}")
    print(f"{'='*60}\n")

    # 1. Fetch data from DB
    print("Fetching recommendation history...")
    papers = fetch_recommendations_from_db(args.user, args.config)
    print(f"  Found {len(papers)} recommendation records")

    # 2. Build sessions
    all_sessions, all_paper_ids = build_sessions(papers)
    print(f"  {len(all_sessions)} sessions with positives, {len(all_paper_ids)} unique papers")

    if len(all_sessions) < 3:
        print(f"\nError: Only {len(all_sessions)} sessions — need at least 3 for pool optimization")
        sys.exit(1)

    # 3. Download PDFs
    tmp_dir = Path(tempfile.mkdtemp(prefix="profile_optimizer_"))
    try:
        print(f"\nDownloading PDFs to {tmp_dir}...")
        pdf_paths = download_pdfs(all_paper_ids, tmp_dir)
        print(f"  Downloaded {len(pdf_paths)}/{len(all_paper_ids)} PDFs")

        if not pdf_paths:
            print("Error: No PDFs downloaded")
            sys.exit(1)

        # 4. Initialize optimizer
        extractor = GeminiProfileExtractor(model_name=args.model)

        if not args.no_eval:
            eval_reranker = GeminiRerankerPDF(
                model_name=args.model,
                prompt_key="personalized_subset_selection_prompt",
                enable_thinking=False,
            )
            evaluator = PoolEvaluator(eval_reranker)
        else:
            evaluator = None

        optimizer = ProfilePoolOptimizer(
            extractor=extractor,
            evaluator=evaluator,
            pool_size=args.pool_size,
            max_mutations=2,
            model_name=args.model,
        )

        # 5. Run pool optimization
        print(f"\nRunning pool optimization...")
        result = optimizer.run_optimization(
            all_sessions=all_sessions,
            pdf_paths_dict=pdf_paths,
            existing_pool=None,
            max_papers=args.max_papers,
            max_val_days=args.max_val_days,
        )

        # 6. Print results
        print_pool_summary(result["pool"])
        for i, c in enumerate(result["pool"]):
            print_profile(c["profile_json"], f"Candidate #{i} (gen {c.get('generation', 0)})")

        if result["active_profile"]:
            print_profile(result["active_profile"], "ACTIVE PROFILE (selected by Pareto front)")

        # 7. Optional: compare with single-profile extraction
        if args.compare_single:
            print(f"\n{'='*60}")
            print(f"  Comparison: Single-Profile Extraction (old behavior)")
            print(f"{'='*60}")
            single_profile, single_usage = extractor.extract_profile(
                all_sessions, pdf_paths, max_papers=args.max_papers
            )
            print_profile(single_profile, "Single-Profile Result")
            print(f"  Tokens: {single_usage.get('total_tokens', 0)}")

        # 8. Save to file
        if args.output:
            output_data = {
                "user": args.user,
                "timestamp": datetime.now().isoformat(),
                "config": {
                    "model": args.model,
                    "max_papers": args.max_papers,
                    "max_val_days": args.max_val_days,
                    "pool_size": args.pool_size,
                },
                "pool": [
                    {
                        "profile_json": c["profile_json"],
                        "precision_val": c.get("precision_val"),
                        "recall_val": c.get("recall_val"),
                        "f1_val": c.get("f1_val"),
                        "val_days_count": c.get("val_days_count"),
                        "generation": c.get("generation"),
                        "mutation_note": c.get("mutation_note"),
                        "is_active": c.get("is_active"),
                    }
                    for c in result["pool"]
                ],
                "active_profile": result["active_profile"],
            }
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            print(f"\nResults saved to {args.output}")

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\nDone. No database writes were made.")


if __name__ == "__main__":
    main()
