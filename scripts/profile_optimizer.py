"""
Standalone profile pool optimizer for interactive tuning.

Runs the same GEPA-style pool optimization as the orchestrator but outputs
results to console and local files — never writes to the database.

Usage:
    # Trajectory simulation (default): shows profile quality evolving over time
    GEMINI_API_KEY=... python scripts/profile_optimizer.py --user "Qi Zhu"

    # Full pool optimization on all data (single run)
    python scripts/profile_optimizer.py --user "Qi Zhu" --full

    # Custom parameters
    python scripts/profile_optimizer.py --user "Qi Zhu" --max-val-days 5

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

from backend.config_utils import load_config
from core.arxiv.downloader import download_pdf
from core.profile_pool import PoolEvaluator, ProfilePoolOptimizer, repack_to_bins
from core.rerankers import GeminiProfileExtractor, GeminiRerankerPDF

# Re-export for visualize_trajectory
__all__ = ["fetch_recommendations_from_db", "build_sessions", "find_like_milestones"]

# 1. Quiet down noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.ERROR)  # Suppresses 'thought_signature' warnings
logging.getLogger("urllib3").setLevel(logging.WARNING)

# 2. Add custom filter to catch specific SDK warnings that skip the logger level
class ThoughtSignatureFilter(logging.Filter):
    def filter(self, record):
        return "thought_signature" not in record.getMessage()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
# Add filter to root logger just in case
logging.getLogger().addFilter(ThoughtSignatureFilter())


def fetch_recommendations_from_db(username: str, config_path: str | None = None) -> list[dict]:
    """Fetch all recommendation records for a user directly from the DB."""
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
    """Group papers into chronological day sessions, keeping only days with likes."""
    sessions_raw = defaultdict(list)
    for p in papers:
        date = (p.get("recommendation_date") or "")[:10]
        if date:
            sessions_raw[date].append(p)

    all_sessions = []
    all_paper_ids = set()
    for day, day_papers in sorted(sessions_raw.items()):
        if any(p.get("blog_liked") is True for p in day_papers):
            candidates = []
            for p in day_papers:
                candidates.append({
                    "paper_id": p["id"],
                    "label": 1 if p.get("blog_liked") is True else 0,
                    "title": p.get("title", ""),
                    "abstract": p.get("abstract", "")
                })
                all_paper_ids.add(p["id"])
            all_sessions.append({"day": day, "candidates": candidates})

    return all_sessions, all_paper_ids




def download_pdfs(paper_ids: set[str], tmp_dir: Path, cache_dir: Path | None = None) -> dict[str, str]:
    """Download PDFs from arXiv, reusing cached files if available.

    Args:
        paper_ids: set of paper IDs to download
        tmp_dir: directory for downloaded files (used if no cache hit)
        cache_dir: persistent cache directory. If set, checks here first and
                   stores newly downloaded files here for reuse across runs.
    """
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths: dict = {}
    for paper_id in paper_ids:
        try:
            arxiv_id = paper_id.split("v")[0] if "v" in paper_id else paper_id
            filename = f"{arxiv_id}.pdf"
            # Check cache first
            if cache_dir:
                cached_path = cache_dir / filename
                if cached_path.exists():
                    pdf_paths[paper_id] = str(cached_path)
                    continue

            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
            path = download_pdf(pdf_url, tmp_dir, filename)
            if path:
                # Copy to cache for future runs
                if cache_dir:
                    import shutil
                    shutil.copy2(str(path), str(cache_dir / filename))
                    pdf_paths[paper_id] = str(cache_dir / filename)
                else:
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
    print("\n  Ranking Heuristics:")
    for h in profile.get("ranking_heuristics", []):
        print(f"    - {h}")
    print("\n  Negative Constraints:")
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


def find_like_milestones(all_sessions: list[dict], step: int = 5) -> list[tuple[int, int]]:
    """Find checkpoints where cumulative likes hit step boundaries.

    Returns list of (session_index, cumulative_likes) — we extract a profile
    using sessions[:session_index+1] and validate on sessions after.
    """
    cumulative = 0
    next_milestone = step
    milestones = []

    for i, session in enumerate(all_sessions):
        likes_in_session = sum(1 for c in session.get("candidates", []) if c.get("label") == 1)
        cumulative += likes_in_session
        if cumulative >= next_milestone:
            milestones.append((i, cumulative))
            next_milestone = ((cumulative // step) + 1) * step

    return milestones


def print_trajectory(trajectory: list[dict]):
    """Print trajectory summary table with GEPA vs Single comparison."""
    print(f"\n{'='*110}")
    print("  Profile Quality Trajectory — GEPA Pool vs Single Re-extraction")
    print("  (evaluated on train+val sessions with time-decay)")
    print(f"{'='*110}")
    print(f"  {'Boost':<6} {'Likes':<6} {'TrainSess':<10} {'EvalSess':<9} "
          f"{'GEPA_F1':<9} {'GEPA_P':<8} {'GEPA_R':<8} "
          f"{'Sing_F1':<9} {'Sing_P':<8} {'Sing_R':<8} {'Delta':<7}")
    print(f"  {'-'*105}")

    for t in trajectory:
        gepa_f1 = f"{t['gepa_f1']:.3f}" if t.get("gepa_f1") is not None else "—"
        gepa_p = f"{t['gepa_precision']:.3f}" if t.get("gepa_precision") is not None else "—"
        gepa_r = f"{t['gepa_recall']:.3f}" if t.get("gepa_recall") is not None else "—"
        sing_f1 = f"{t['single_f1']:.3f}" if t.get("single_f1") is not None else "—"
        sing_p = f"{t['single_precision']:.3f}" if t.get("single_precision") is not None else "—"
        sing_r = f"{t['single_recall']:.3f}" if t.get("single_recall") is not None else "—"

        delta = ""
        if t.get("gepa_f1") is not None and t.get("single_f1") is not None:
            d = t["gepa_f1"] - t["single_f1"]
            delta = f"+{d:.3f}" if d >= 0 else f"{d:.3f}"

        print(
            f"  #{t['step']:<5} {t['cumulative_likes']:<6} {t['train_sessions']:<10} "
            f"{t.get('eval_sessions', 0):<9} "
            f"{gepa_f1:<9} {gepa_p:<8} {gepa_r:<8} "
            f"{sing_f1:<9} {sing_p:<8} {sing_r:<8} {delta:<7}"
        )
    print()


def run_trajectory(
    all_sessions: list[dict],
    pdf_paths: dict[str, str],
    extractor: GeminiProfileExtractor,
    evaluator: PoolEvaluator | None,
    optimizer: ProfilePoolOptimizer,
    max_val_bins: int,
    pool_size: int,
    decay: float | None = None,
    max_boosts: int | None = None,
    debug: bool = False,
) -> list[dict]:
    """Run dual-track trajectory: GEPA pool evolution vs single re-extraction.

    At each 5-like milestone, both approaches are evaluated on the same data:
    - Train+val sessions (current training + previous training = anti-forgetting + learning)

    Data flow per boost:
        Boost #1: train=[sessions 1-5], eval_sessions=[]  (no prior data)
        Boost #2: train=[sessions 6-10], eval_sessions=[1-5]  (previous train)
        Boost #3: train=[sessions 11-14], eval_sessions=[6-10] (previous train)
        ...

    GEPA path: pool evolves with performance feedback → mutation with TP/FP/FN breakdown
    Single path: re-extract from current training only, no memory
    """
    milestones = find_like_milestones(all_sessions, step=5)

    if not milestones:
        print("  No milestones found (need at least 5 cumulative likes)")
        return []

    if max_boosts:
        milestones = milestones[:max_boosts]

    print(f"\n  Found {len(milestones)} boost checkpoints:")
    for idx, (sess_idx, cum_likes) in enumerate(milestones):
        day = all_sessions[sess_idx]["day"]
        prev_sess = milestones[idx - 1][0] if idx > 0 else -1
        new_sessions = sess_idx - prev_sess
        print(f"    Boost #{idx+1}: {cum_likes} cumulative likes by {day} "
              f"({new_sessions} new sessions, #{prev_sess+2}..#{sess_idx+1})")

    trajectory = []
    previous_pool = None
    prev_breakdown = None
    prev_gepa_f1 = None

    for step_idx, (session_cutoff, cumulative_likes) in enumerate(milestones):
        boost_num = step_idx + 1

        # Training = sessions with the NEW likes since last milestone
        prev_cutoff = milestones[step_idx - 1][0] if step_idx > 0 else -1
        train_sessions = all_sessions[prev_cutoff + 1 : session_cutoff + 1]
        train_paper_ids = set()
        for s in train_sessions:
            for c in s.get("candidates", []):
                train_paper_ids.add(c["paper_id"])

        # Evaluation track: repack all sessions seen so far into bins of 20
        all_eval_history = all_sessions[: session_cutoff + 1]
        eval_bins = repack_to_bins(all_eval_history, bin_size=20)

        # Cap to max_val_bins if history is too large
        if len(eval_bins) > max_val_bins:
            eval_bins = eval_bins[-max_val_bins:]

        # Build PDF paths for training papers
        train_pdf_paths = {pid: pdf_paths[pid] for pid in train_paper_ids if pid in pdf_paths}

        print(f"\n{'='*70}")
        print(f"  Boost #{boost_num} — {cumulative_likes} cumulative likes")
        print(f"{'='*70}")
        print(f"  Training: {len(train_sessions)} day sessions ({', '.join(s['day'] for s in train_sessions)})")
        print(f"  Evaluation: {len(eval_bins)} standardized bins (repacked from {len(all_eval_history)} days)")

        if not train_pdf_paths:
            print("  Skipping — no training PDFs available")
            continue

        # ── GEPA PATH: pool evolution with performance feedback ──
        print("\n  --- GEPA Pool Evolution ---")
        gepa_result = optimizer.run_optimization(
            train_sessions=train_sessions,
            val_bins=eval_bins,
            pdf_paths_dict=pdf_paths,
            existing_pool=previous_pool,
            max_papers=len(train_paper_ids),
            performance_breakdown=prev_breakdown,
            previous_f1=prev_gepa_f1,
            max_val_days=7,
        )

        # We no longer redundantly re-evaluate the active profile since it was perfectly evaluated inside run_optimization
        gepa_metrics = gepa_result.get("active_metrics") or {"precision": None, "recall": None, "f1": None, "val_days": 0}
        gepa_breakdown = gepa_result.get("active_breakdown")

        if gepa_metrics.get("precision") is not None:
            print(f"  GEPA eval: P={gepa_metrics['precision']:.3f} R={gepa_metrics['recall']:.3f} "
                f"F1={gepa_metrics['f1']:.3f} ({gepa_metrics['val_days']} bins, uniform)")
        else:
            print("  GEPA eval: skipped (no active profile or evaluation disabled)")

        if gepa_result["active_profile"]:
            persona = gepa_result["active_profile"].get("persona_definition", "N/A")
            print(f"  GEPA persona: {persona[:90]}...")

        # ── SINGLE PATH: re-extract from scratch ──
        if step_idx > 0:
            print("\n  --- Single Re-extraction (baseline) ---")

            # We need the PDF mapping explicitly for the baseline evaluation
            all_eval_pdfs = {}
            for s in eval_bins:
                for c in s.get("candidates", []):
                    pid = c["paper_id"]
                    if pid in pdf_paths:
                        all_eval_pdfs[pid] = pdf_paths[pid]

            single_profile = None
            single_metrics = {"precision": None, "recall": None, "f1": None, "val_days": 0}
            try:
                single_profile, single_usage = extractor.extract_profile(
                    train_sessions, train_pdf_paths, max_papers=len(train_paper_ids)
                )
                print(f"  Single extraction: {single_usage.get('total_tokens', 0)} tokens")

                # Evaluate single profile comprehensively (atomic loop for KV cache)
                if evaluator and eval_bins and all_eval_pdfs and single_profile:
                    single_results = []
                    for bin_item in eval_bins:
                        res_s = evaluator.evaluate_single_day(single_profile, bin_item, all_eval_pdfs)
                        if res_s:
                            single_results.append(res_s)

                    agg_s = evaluator.aggregate_results(single_results)
                    single_metrics = {
                        "precision": agg_s["precision"],
                        "recall": agg_s["recall"],
                        "f1": agg_s["f1"],
                        "val_days": agg_s["val_days_count"],
                    }
                    print(f"  Single eval: P={single_metrics['precision']:.3f} R={single_metrics['recall']:.3f} "
                        f"F1={single_metrics['f1']:.3f} ({single_metrics['val_days']} bins, uniform)")
                else:
                    print(f"  Single eval: skipped ({'no eval data' if not all_eval_pdfs else 'evaluator disabled'})")
            except Exception as e:
                print(f"  Single extraction failed: {e}")
        else:
            single_profile = gepa_result["active_profile"]
            single_metrics = gepa_metrics

        # Record trajectory point
        trajectory.append({
            "step": boost_num,
            "cumulative_likes": cumulative_likes,
            "train_sessions": len(train_sessions),
            "train_papers": len(train_paper_ids),
            "eval_bins": len(eval_bins),
            "boost_num": boost_num,
            # GEPA metrics
            "gepa_precision": gepa_metrics["precision"],
            "gepa_recall": gepa_metrics["recall"],
            "gepa_f1": gepa_metrics["f1"],
            # Single metrics
            "single_precision": single_metrics["precision"],
            "single_recall": single_metrics["recall"],
            "single_f1": single_metrics["f1"],
            # Profiles
            "gepa_profile": gepa_result["active_profile"],
            "single_profile": single_profile,
            "pool": gepa_result["pool"],
        })

        # Carry forward for next boost
        previous_pool = gepa_result["pool"]
        prev_breakdown = gepa_breakdown
        prev_gepa_f1 = gepa_metrics.get("f1")

    return trajectory

def main():
    parser = argparse.ArgumentParser(description="Standalone profile pool optimizer (no DB writes)")
    parser.add_argument("--user", required=True, help="Username to optimize profile for")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini model (default: gemini-3-flash-preview)")
    parser.add_argument("--eval-model", default="gemini-3.1-flash-lite-preview", help="Gemini model used for evaluation (default: gemini-3.1-flash-lite-preview)")
    parser.add_argument("--max-papers", type=int, default=50, help="Max papers for training in --full mode (default: 50)")
    parser.add_argument("--max-val-bins", type=int, default=30, help="Max history bins for evaluation per checkpoint (default: 30)")
    parser.add_argument("--pool-size", type=int, default=3, help="Max pool size (default: 3)")
    parser.add_argument("--full", action="store_true", help="Run full optimization on all data (skip trajectory)")
    parser.add_argument("--no-eval", action="store_true", help="Skip evaluation (extraction only)")
    parser.add_argument("--decay", type=float, default=None, help="Time-decay weight for evaluation (default: 0.85)")
    parser.add_argument("--compare-single", action="store_true", help="Also run single-profile extraction for comparison")
    parser.add_argument("--output", type=str, default=None, help="Save results to JSON file")
    parser.add_argument("--cache-dir", type=str, default=None, help="Persistent PDF cache directory (reuse across runs)")
    parser.add_argument("--config", type=str, default=None, help="Backend config path (for DB connection)")
    parser.add_argument("--max-boosts", type=int, default=None, help="Max number of boosts to run (for debugging)")
    parser.add_argument("--debug", action="store_true", help="Print full rendered prompts for each step")
    parser.add_argument("--write-db", action="store_true", help="Write final pool to database via backend API (pool + boost history)")
    args = parser.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable required")
        sys.exit(1)

    mode = "full" if args.full else "trajectory"
    print(f"\n{'='*60}")
    print(f"  Profile Pool Optimizer — {args.user}")
    print(f"  Model: {args.model}")
    print(f"  Eval Model: {args.eval_model}")
    print(f"  Mode: {mode}")
    if args.full:
        print(f"  Max papers: {args.max_papers}")
    print(f"  Max val bins: {args.max_val_bins}")
    print(f"  Pool size: {args.pool_size}, Eval: {not args.no_eval}")
    print(f"{'='*60}\n")

    # 1. Fetch data from DB
    print("Fetching recommendation history...")
    papers = fetch_recommendations_from_db(args.user, args.config)
    print(f"  Found {len(papers)} recommendation records")

    # 2. Build sessions (only days with at least 1 like)
    all_sessions, all_paper_ids = build_sessions(papers)
    total_likes = sum(
        1 for s in all_sessions for c in s.get("candidates", []) if c.get("label") == 1
    )
    print(f"  {len(all_sessions)} sessions with likes, {total_likes} total likes, {len(all_paper_ids)} unique papers")

    if not args.full and total_likes < 5:
        print(f"\nError: Only {total_likes} likes — need at least 5 for trajectory simulation")
        sys.exit(1)
    if args.full and len(all_sessions) < 3:
        print(f"\nError: Only {len(all_sessions)} sessions with positives — need at least 3 for pool optimization")
        sys.exit(1)

    # 3. Download PDFs
    tmp_dir = Path(tempfile.mkdtemp(prefix="profile_optimizer_"))
    try:
        print(f"\nDownloading PDFs to {tmp_dir}...")
        cache_dir = Path(args.cache_dir) if args.cache_dir else None
        pdf_paths = download_pdfs(all_paper_ids, tmp_dir, cache_dir=cache_dir)
        print(f"  Downloaded {len(pdf_paths)}/{len(all_paper_ids)} PDFs")

        if not pdf_paths:
            print("Error: No PDFs downloaded")
            sys.exit(1)

        # 4. Initialize components
        extractor = GeminiProfileExtractor(model_name=args.model)

        # Use a hidden .cache directory for initial pool caching
        profile_cache_dir = project_root / ".cache" / "initial_pools"

        if not args.no_eval:
            eval_reranker = GeminiRerankerPDF(
                model_name=args.eval_model,
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
            cache_dir=profile_cache_dir,
            debug=args.debug,
        )

        if True:
            trajectory = run_trajectory(
                all_sessions, pdf_paths, extractor, evaluator, optimizer,
                max_val_bins=args.max_val_bins,
                pool_size=args.pool_size,
                decay=args.decay,
                max_boosts=args.max_boosts,
                debug=args.debug,
            )

            # Print final trajectory table
            print_trajectory(trajectory)

            # Print profiles from each boost
            for t in trajectory:
                if t.get("gepa_profile"):
                    print_profile(
                        t["gepa_profile"],
                        f"GEPA Boost #{t['boost_num']} ({t['cumulative_likes']} likes, F1={t.get('gepa_f1', 'N/A')})",
                    )
                if t.get("single_profile"):
                    print_profile(
                        t["single_profile"],
                        f"Single Boost #{t['boost_num']} ({t['cumulative_likes']} likes, F1={t.get('single_f1', 'N/A')})",
                    )

            # Save to file
            if args.output and trajectory:
                _save_output(args, result=None, trajectory=trajectory)

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\nDone.")

    # Write to database if requested
    if args.write_db and trajectory:
        _write_pool_to_db(args, trajectory)


def _write_pool_to_db(args, trajectory: list[dict]):
    """Write the final boost's pool to the backend API (pool + boost history)."""
    import requests as http_requests

    config = load_config(args.config)
    app_config = config.get("APP_SERVICE", {})
    host = app_config.get("host", "http://localhost:8000")

    # Use the LAST boost's pool as the current active pool
    last = trajectory[-1]
    pool = last.get("pool", [])
    if not pool:
        print("  No pool to write — skipping DB write.")
        return

    # Find active entry index
    active_idx = 0
    for i, entry in enumerate(pool):
        if entry.get("is_active"):
            active_idx = i
            break

    active = pool[active_idx]

    # 1. Save profile pool
    entries = []
    for c in pool:
        entries.append({
            "profile_json": c.get("profile_json"),
            "generation": c.get("generation", 0),
            "parent_id": c.get("parent_id"),
            "mutation_note": c.get("mutation_note"),
            "breakdown_str": c.get("breakdown_str"),
            "is_active": c.get("is_active", False),
            "precision_val": c.get("precision_val"),
            "recall_val": c.get("recall_val"),
            "f1_val": c.get("f1_val"),
            "val_days_count": c.get("val_days_count", 0),
        })

    try:
        resp = http_requests.post(
            f"{host}/api/users/profile-pool/{args.user}",
            json={"entries": entries, "active_entry_index": active_idx},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"  ✓ Saved pool to DB: {len(entries)} entries, active gen={active.get('generation', 0)}")
    except Exception as e:
        print(f"  ✖ Failed to save pool: {e}")
        return

    # 2. Record boost history for each trajectory step
    for t in trajectory:
        gepa_profile = t.get("gepa_profile") or {}
        changes_made = gepa_profile.get("changes_made")
        pool_at_step = t.get("pool", [])
        pool_diversity = [
            {
                "id": c.get("id"),
                "gen": c.get("generation", 0),
                "f1": c.get("f1_val"),
                "note": (c.get("mutation_note") or "")[:60],
            }
            for c in pool_at_step
        ]
        try:
            resp = http_requests.post(
                f"{host}/api/users/boost-history/{args.user}",
                json={
                    "boost_number": 0,
                    "cumulative_likes": t["cumulative_likes"],
                    "pool_version": 0,
                    "precision": t.get("gepa_precision"),
                    "recall": t.get("gepa_recall"),
                    "f1": t.get("gepa_f1"),
                    "active_profile_json": gepa_profile,
                    "changes_made": changes_made,
                    "pool_candidates_count": len(pool_at_step),
                    "pool_diversity": pool_diversity,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"  ✖ Failed to record boost history for step {t['step']}: {e}")

    print(f"  ✓ Recorded {len(trajectory)} boost history entries")


def _save_output(args, result: dict | None, trajectory: list[dict] | None):
    """Save results to JSON file."""
    output_data = {
        "user": args.user,
        "timestamp": datetime.now().isoformat(),
        "mode": "trajectory" if trajectory else "full",
        "config": {
            "model": args.model,
            "max_val_bins": args.max_val_bins,
            "pool_size": args.pool_size,
            "decay": args.decay,
        },
    }

    if trajectory:
        output_data["trajectory"] = [
            {
                "step": t["step"],
                "cumulative_likes": t["cumulative_likes"],
                "train_sessions": t["train_sessions"],
                "train_papers": t["train_papers"],
                "eval_sessions": t.get("eval_sessions", 0),
                "boost_num": t.get("boost_num"),
                "gepa_precision": t.get("gepa_precision"),
                "gepa_recall": t.get("gepa_recall"),
                "gepa_f1": t.get("gepa_f1"),
                "single_precision": t.get("single_precision"),
                "single_recall": t.get("single_recall"),
                "single_f1": t.get("single_f1"),
                "gepa_profile": t.get("gepa_profile"),
                "single_profile": t.get("single_profile"),
                "pool_size": len(t.get("pool", [])),
            }
            for t in trajectory
        ]
    elif result:
        output_data["config"]["max_papers"] = args.max_papers
        output_data["pool"] = [
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
        ]
        output_data["active_profile"] = result["active_profile"]

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
