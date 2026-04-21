"""GEPA-inspired profile pool optimization for personalized paper recommendations.

Maintains a pool of candidate user profiles, evaluates them on held-out validation
data (rolling window), and evolves them via reflective mutation using Pareto-front
selection across precision and recall.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from google import genai

from .rerankers import GeminiProfileExtractor, GeminiRerankerPDF

logger = logging.getLogger(__name__)



def calculate_f1(predicted: set[str], actual: set[str]) -> dict[str, float]:
    """Calculate Precision, Recall, F1."""
    if not predicted and not actual:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not predicted or not actual:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    tp = len(predicted & actual)
    precision = tp / len(predicted)
    recall = tp / len(actual)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def repack_to_bins(sessions: list[dict], bin_size: int = 20) -> list[dict]:
    """Flattens sessions and repacks papers into fixed-size bins for evaluation."""
    all_candidates = []
    for s in sessions:
        all_candidates.extend(s["candidates"])

    if not all_candidates:
        return []

    MIN_LAST_BIN = 5
    bins = []

    for i in range(0, len(all_candidates), bin_size):
        chunk = all_candidates[i : i + bin_size]

        # Merge tiny last bin
        if i > 0 and len(chunk) < MIN_LAST_BIN and bins:
            bins[-1]["candidates"].extend(chunk)
            continue

        bins.append({
            "day": f"Bin {len(bins) + 1} ({len(chunk)} papers)",
            "candidates": chunk
        })
    return bins


class PoolEvaluator:
    """Evaluate a candidate profile on held-out validation data using F1 metric."""

    def __init__(self, reranker: GeminiRerankerPDF):
        self.reranker = reranker

    def evaluate(
        self,
        profile: dict,
        val_days: list[dict],
        pdf_paths_dict: dict[str, str],
        max_val_days: int = 7,
        decay: float | None = None,
    ) -> dict:
        """
        Evaluate a profile on validation days.

        Args:
            profile: {persona_definition, negative_constraints, ranking_heuristics}
            val_days: [{day, candidates: [{paper_id, label, title, abstract}]}]
            pdf_paths_dict: paper_id → local PDF path
            max_val_days: max validation days to evaluate (cost control)
            decay: exponential decay weight for recent sessions (e.g. 0.85).
                   None = equal weighting.

        Returns:
            {precision, recall, f1, val_days_count, per_day_breakdown,
             breakdown_str, tp_paper_ids, fp_paper_ids, fn_paper_ids}
        """
        sampled_days = val_days[:max_val_days]
        results = []

        logger.info(f"⚡ Starting evaluation of {len(sampled_days)} days in parallel...")

        def _evaluate_day(day_item):
            day_str = day_item["day"]
            candidates = day_item["candidates"]
            actual_positives = {c["paper_id"] for c in candidates if c.get("label") == 1}

            if not actual_positives:
                return None

            # Build PDF paths for this day's candidates
            day_pdf_paths = {
                c["paper_id"]: pdf_paths_dict[c["paper_id"]]
                for c in candidates
                if c["paper_id"] in pdf_paths_dict
            }

            if not day_pdf_paths:
                logger.warning(f"⚠ Day {day_str}: no PDFs available, skipping")
                return None

            logger.info(f"→ {day_str}: evaluating {len(day_pdf_paths)} papers...")

            import time

            max_retries = 3
            backoff = 5
            for attempt in range(max_retries):
                try:
                    ranked, _ = self.reranker.rerank(
                        query="",
                        pdf_paths_dict=day_pdf_paths,
                        retrieve_ids=list(day_pdf_paths.keys()),
                        top_k=len(day_pdf_paths),
                        user_profile=profile,
                    )
                    predicted = set(ranked) if ranked else set()
                    logger.info(f"✓ {day_str}: predicted {len(predicted)} pos out of {len(day_pdf_paths)}")
                    break
                except Exception as e:
                    error_str = str(e).lower()
                    is_retryable = any(err in error_str for err in ["503", "unavailable", "429"])
                    if is_retryable and attempt < max_retries - 1:
                        wait = backoff ** (attempt + 1)
                        logger.warning(f"⚠ {day_str}: retryable error, attempt {attempt+1}/{max_retries}, retrying in {wait}s: {e}")
                        time.sleep(wait)
                    else:
                        logger.error(f"✖ {day_str}: evaluation failed after {max_retries} retries: {e}")
                        predicted = set()
                        break

            # Compute TP/FP/FN per day
            tp_ids = predicted & actual_positives
            fp_ids = predicted - actual_positives
            fn_ids = actual_positives - predicted

            # Build lookup for title/abstract
            cand_lookup = {c["paper_id"]: c for c in candidates}

            metrics = calculate_f1(predicted, actual_positives)
            return {
                "day": day_str,
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "f1": metrics["f1"],
                "num_candidates": len(candidates),
                "num_actual": len(actual_positives),
                "num_predicted": len(predicted),
                "tp_ids": tp_ids,
                "fp_ids": fp_ids,
                "fn_ids": fn_ids,
                "candidates": candidates,
                "cand_lookup": cand_lookup,
            }

        for day_item in sampled_days:
            try:
                res = _evaluate_day(day_item)
                if res is not None:
                    results.append(res)
            except Exception as exc:
                logger.error(f"Day {day_item['day']} generated an exception: {exc}")

        # Sort results by day to maintain chronological order
        results.sort(key=lambda x: x["day"])

        if not results:
            return {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "val_days_count": 0,
                "per_day_breakdown": [],
                "breakdown_str": "",
                "tp_paper_ids": set(),
                "fp_paper_ids": set(),
                "fn_paper_ids": set(),
            }

        # Compute weighted averages
        n = len(results)
        if decay is not None and n > 1:
            weights = [decay ** (n - 1 - i) for i in range(n)]
            total_weight = sum(weights)
            avg_precision = sum(r["precision"] * w for r, w in zip(results, weights)) / total_weight
            avg_recall = sum(r["recall"] * w for r, w in zip(results, weights)) / total_weight
            avg_f1 = sum(r["f1"] * w for r, w in zip(results, weights)) / total_weight
        else:
            avg_precision = sum(r["precision"] for r in results) / n
            avg_recall = sum(r["recall"] for r in results) / n
            avg_f1 = sum(r["f1"] for r in results) / n

        # Aggregate TP/FP/FN across all days
        all_tp = set()
        all_fp = set()
        all_fn = set()
        for r in results:
            all_tp |= r["tp_ids"]
            all_fp |= r["fp_ids"]
            all_fn |= r["fn_ids"]

        # Build rich breakdown string for refinement prompt
        breakdown_str = self._build_breakdown_str(results)

        return {
            "precision": avg_precision,
            "recall": avg_recall,
            "f1": avg_f1,
            "val_days_count": n,
            "per_day_breakdown": results,
            "breakdown_str": breakdown_str,
            "tp_paper_ids": all_tp,
            "fp_paper_ids": all_fp,
            "fn_paper_ids": all_fn,
        }

    def _build_breakdown_str(self, results: list[dict]) -> str:
        """Build rich TP/FP/FN breakdown string for the refinement prompt."""
        parts = []
        for r in results:
            cand_lookup = r.get("cand_lookup", {})
            parts.append(f"### Session: {r['day']} (Precision: {r['precision']:.1%}, Recall: {r['recall']:.1%})")
            parts.append("")

            # True Positives
            tp_ids = r.get("tp_ids", set())
            if tp_ids:
                parts.append("**True Positives (correctly selected — PRESERVE):**")
                for pid in sorted(tp_ids):
                    c = cand_lookup.get(pid, {})
                    title = c.get("title", "N/A")
                    abstract = c.get("abstract", "").replace("\n", " ")
                    parts.append(f'- "{title}"')
                    if abstract:
                        parts.append(f'  *Abstract:* "{abstract}..."')
            else:
                parts.append("**True Positives:** (none)")

            # False Positives
            fp_ids = r.get("fp_ids", set())
            if fp_ids:
                parts.append("")
                parts.append("**False Positives (selected but DISLIKED — HURTS PRECISION):**")
                for pid in sorted(fp_ids):
                    c = cand_lookup.get(pid, {})
                    title = c.get("title", "N/A")[:80]
                    abstract = c.get("abstract", "")[:120].replace("\n", " ")
                    parts.append(f'- "{title}"')
                    if abstract:
                        parts.append(f'  *Snippet:* "{abstract}..."')
            else:
                parts.append("")
                parts.append("**False Positives:** (none — good precision!)")

            # False Negatives
            fn_ids = r.get("fn_ids", set())
            if fn_ids:
                parts.append("")
                parts.append("**False Negatives (missed but LIKED — HURTS RECALL):**")
                for pid in sorted(fn_ids):
                    c = cand_lookup.get(pid, {})
                    title = c.get("title", "N/A")[:80]
                    abstract = c.get("abstract", "")[:120].replace("\n", " ")
                    parts.append(f'- "{title}"')
                    if abstract:
                        parts.append(f'  *Snippet:* "{abstract}..."')
            else:
                parts.append("")
                parts.append("**False Negatives:** (none — good recall!)")

            parts.append("")

        return "\n".join(parts)


class ParetoFront:
    """Maintain non-dominated candidates across precision and recall."""

    @staticmethod
    def compute(candidates: list[dict]) -> list[dict]:
        """Return only non-dominated candidates.

        A candidate dominates another if it is >= on both precision and recall
        and strictly > on at least one.
        """
        if not candidates:
            return []

        non_dominated = []
        for i, c in enumerate(candidates):
            p_i = c.get("precision_val") or 0.0
            r_i = c.get("recall_val") or 0.0
            dominated = False
            for j, other in enumerate(candidates):
                if i == j:
                    continue
                p_j = other.get("precision_val") or 0.0
                r_j = other.get("recall_val") or 0.0
                # other dominates c if other >= on both AND strictly > on one
                if p_j >= p_i and r_j >= r_i and (p_j > p_i or r_j > r_i):
                    dominated = True
                    break
            if not dominated:
                non_dominated.append(c)

        return non_dominated

    @staticmethod
    def select_active(candidates: list[dict]) -> dict | None:
        """From the Pareto front, pick highest F1. Tiebreak: newer generation."""
        front = ParetoFront.compute(candidates)
        if not front:
            return None
        return max(
            front,
            key=lambda c: (c.get("f1_val") or 0.0, c.get("generation") or 0),
        )


class ProfilePoolOptimizer:
    """Orchestrate the GEPA-style profile pool optimization loop."""

    def __init__(
        self,
        extractor: GeminiProfileExtractor,
        evaluator: PoolEvaluator,
        pool_size: int = 5,
        max_mutations: int = 2,
        model_name: str = "gemini-3-flash-preview",
        debug: bool = False,
        cache_dir: Path | str | None = None,
    ):
        self.extractor = extractor
        self.evaluator = evaluator
        self.pool_size = pool_size
        self.max_mutations = max_mutations
        self.model_name = model_name
        self.debug = debug
        self.cache_dir = Path(cache_dir) if cache_dir else None

        api_key = _get_gemini_key()
        self.client = genai.Client(api_key=api_key)

        # Load prompts and variants
        prompt_path = Path(__file__).parent / "prompts" / "rerank_prompts.yaml"
        with open(prompt_path) as f:
            prompts = yaml.safe_load(f)
        self.refinement_prompt = prompts.get("profile_refinement_prompt", "")
        self.extraction_prompt = prompts.get("profile_extraction_prompt", "")
        self.variants = prompts.get("initial_pool_variants", {})

    def _dump_payload(self, call_type: str, payload: dict):
        """Append Gemini API input payload to mutation_payloads.log as JSON."""
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "type": call_type,
                "model": self.model_name,
                **payload,
            }
            with open("mutation_payloads.log", "a") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    def run_optimization(
        self,
        train_sessions: list[dict],
        val_bins: list[dict],
        pdf_paths_dict: dict[str, str],
        existing_pool: list[dict] | None = None,
        max_papers: int = 50,
        performance_breakdown: str | None = None,
        previous_f1: float | None = None,
        fast_init: bool = False,
    ) -> dict:
        """
        Run the full optimization loop.

        Args:
            train_sessions: chronological day sessions with NEW likes for this boost's training
            val_bins: fully repacked, standardized 20-paper bins for trajectory evaluation
            pdf_paths_dict: paper_id → local PDF path
            existing_pool: existing pool entries from DB (may be empty/None)
            max_papers: max PDF pages for training
            performance_breakdown: rich TP/FP/FN breakdown from previous evaluation
            previous_f1: F1 score from previous boost's evaluation
            fast_init: if True, skips evaluation on the first boost and picks an arbitrary active profile

        Returns:
            {pool: [...], active_profile: {...}, active_metrics: {...}, ...}
        """
        if not train_sessions:
            logger.warning("No training sessions available")
            return {"pool": [], "active_profile": None, "active_id": None}

        is_first_boost = not existing_pool

        if is_first_boost:
            logger.info("First boost — initializing pool with 3 candidates")
            candidates = self._initialize_pool(train_sessions, pdf_paths_dict, max_papers)
        else:
            logger.info("Subsequent boost — evolving existing pool of %d candidates", len(existing_pool))
            candidates = self._evolve_pool(
                existing_pool, train_sessions, pdf_paths_dict, max_papers,
                performance_breakdown=performance_breakdown,
                previous_f1=previous_f1,
            )

        if is_first_boost and fast_init:
            logger.info("Fast Init enabled: Skipping evaluation for first boost. Selecting arbitrary profile.")
            for c in candidates:
                c["precision_val"] = 0.0
                c["recall_val"] = 0.0
                c["f1_val"] = 0.0
                c["val_days_count"] = len(val_bins)
                c["breakdown_str"] = "Skipped evaluation on first boost (fast-init)."
        else:
            logger.info("Evaluating %d candidates on %d standardized bins", len(candidates), len(val_bins))
            candidates = self._evaluate_all(candidates, val_bins, pdf_paths_dict, len(val_bins))

        # Compute Pareto front and prune
        active = ParetoFront.select_active(candidates)
        if active is None:
            # Fallback: pick the newest candidate
            logger.error("No active profile found, selecting newest candidate")

        # Mark active
        for c in candidates:
            c["is_active"] = c is active

        # Prune to pool_size
        pool = self._prune_pool(candidates)

        logger.info(
            "Pool optimization complete: %d candidates, active F1=%.3f (gen %d)",
            len(pool),
            active.get("f1_val") or 0.0,
            active.get("generation", 0),
        )

        return {
            "pool": pool,
            "active_profile": active["profile_json"] if active else None,
            "active_metrics": {
                "precision": active.get("precision_val", 0.0),
                "recall": active.get("recall_val", 0.0),
                "f1": active.get("f1_val", 0.0),
                "val_days": active.get("val_days_count", 0),
            } if active else None,
            "active_breakdown": active.get("breakdown_str") if active else None,
            "active_id": active.get("id") if active else None,
        }

    def _initialize_pool(
        self,
        train_sessions: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
    ) -> list[dict]:
        """First boost: extract 1 base profile + 2 variants."""
        # Check cache
        cache_file = None
        if self.cache_dir:
            import hashlib
            # Create a stable key from paper IDs in the first boost
            all_pids = []
            for s in train_sessions:
                for c in s.get("candidates", []):
                    all_pids.append(c["paper_id"])

            # Hash the sorted IDs to ensure deterministic key
            hash_key = hashlib.sha256(",".join(sorted(all_pids)).encode()).hexdigest()[:16]
            cache_file = self.cache_dir / f"pool_init_{hash_key}.json"

            if cache_file.exists():
                try:
                    with open(cache_file, "r") as f:
                        cached_candidates = json.load(f)
                    logger.info("Loaded 3 initial candidates from cache: %s", cache_file.name)
                    return cached_candidates
                except Exception as e:
                    logger.warning("Failed to load initial pool cache: %s", e)

        candidates = []

        # If no variants in YAML, fallback to a single default run
        variant_items = self.variants.items() if self.variants else [("default", "")]

        for variant_name, framing_suffix in variant_items:
            profile, usage = self._extract_with_framing(
                train_sessions, pdf_paths_dict, max_papers, framing_suffix
            )
            candidates.append({
                "id": f"gen0_{uuid.uuid4().hex[:8]}",
                "profile_json": profile,
                "generation": 0,
                "mutation_note": f"Initial extraction (variant: {variant_name})",
                "is_active": False,
                "precision_val": None,
                "recall_val": None,
                "f1_val": None,
                "val_days_count": 0,
            })
            logger.info(
                "Extracted variant '%s' (%d tokens)",
                variant_name,
                usage.get("total_tokens", 0),
            )

        # Save to cache
        if cache_file:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w") as f:
                    json.dump(candidates, f, indent=2)
                logger.info("Saved initial pool to cache: %s", cache_file.name)
            except Exception as e:
                logger.warning("Failed to save initial pool cache: %s", e)

        return candidates

    def _extract_with_framing(
        self,
        training_data: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
        framing_suffix: str | None,
    ) -> tuple[dict, dict]:
        """Extract a profile with an optional framing suffix appended to the prompt."""
        contents = self.extractor._build_pdf_contents(training_data, pdf_paths_dict, max_papers)

        prompt_text = self.extraction_prompt.format(
            training_examples="[PDF papers are provided above with their IDs and labels]"
        )
        if framing_suffix:
            prompt_text += framing_suffix

        contents.append(prompt_text)

        if self.debug:
            print(f"\n{'─'*70}")
            print(f"  [DEBUG] EXTRACTION PROMPT (variant: {framing_suffix or 'default'})")
            print(f"{'─'*70}")
            text_parts = [c for c in contents if isinstance(c, str)]
            pdf_count = len(contents) - len(text_parts)
            print(f"  PDF pages: {pdf_count}, Text parts: {len(text_parts)}")
            print(f"  Prompt text (last {len(prompt_text)} chars):")
            print(prompt_text[:2000])
            if len(prompt_text) > 2000:
                print(f"  ... (truncated, {len(prompt_text)} total chars)")
            print(f"{'─'*70}\n")

        self._dump_payload("extraction", {
            "variant": framing_suffix or "default",
            "prompt_text": prompt_text,
            "num_pdf_pages": sum(1 for c in contents if not isinstance(c, str)),
        })

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
            )
            profile = self.extractor._parse_json_response(response.text)
            usage = {
                "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) or 0,
            }
            if self.debug:
                print(f"  [DEBUG] EXTRACTION RESPONSE ({len(response.text)} chars):")
                print(response.text[:3000])
                print()
            return profile, usage
        except Exception as e:
            logger.warning("Profile extraction attempt failed: %s — retrying in 30s", e)
            import time
            time.sleep(30)
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                )
                profile = self.extractor._parse_json_response(response.text)
                usage = {
                    "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                    "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) or 0,
                }
                return profile, usage
            except Exception as e2:
                logger.error("Profile extraction failed after retry: %s", e2)
                # No more generic fallback JSON. Let it fail so the user knows something is wrong.
                raise e2

    def _evolve_pool(
        self,
        existing_pool: list[dict],
        train_sessions: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
        performance_breakdown: str | None = None,
        previous_f1: float | None = None,
    ) -> list[dict]:
        """Subsequent boost: re-evaluate existing + mutate top-2."""
        # Start with existing candidates (reset metrics — they'll be re-evaluated)
        candidates = []
        for entry in existing_pool:
            candidates.append({
                "id": entry.get("id"),
                "profile_json": entry["profile_json"],
                "generation": entry.get("generation", 0),
                "mutation_note": entry.get("mutation_note"),
                "is_active": False,
                "precision_val": None,
                "recall_val": None,
                "f1_val": None,
                "val_days_count": 0,
                "parent_id": entry.get("parent_id"),
                "prev_breakdown_str": entry.get("breakdown_str"),
                "prev_f1": entry.get("f1_val"),
            })

        # Sort existing by previous F1 (if available) for mutation selection
        scored = [c for c in candidates if c.get("prev_f1") is not None]
        if not scored:
            scored = candidates

        top_candidates = sorted(
            scored,
            key=lambda c: c.get("prev_f1") or 0.0,
            reverse=True,
        )[:self.max_mutations]

        # Mutate top candidates via profile_refinement_prompt
        for parent in top_candidates:
            mutated_profile = self._mutate_profile(
                parent["profile_json"],
                train_sessions,
                pdf_paths_dict,
                max_papers,
                performance_breakdown=parent.get("prev_breakdown_str") or performance_breakdown,
                previous_f1=parent.get("prev_f1"),
            )
            if mutated_profile:
                candidates.append({
                    "id": f"gen{parent.get('generation', 0) + 1}_{uuid.uuid4().hex[:8]}",
                    "profile_json": mutated_profile,
                    "generation": parent.get("generation", 0) + 1,
                    "parent_id": parent.get("id"),
                    "mutation_note": f"Reflective mutation from gen {parent.get('generation', 0)} (parent: {parent.get('id')})",
                    "is_active": False,
                    "precision_val": None,
                    "recall_val": None,
                    "f1_val": None,
                    "val_days_count": 0,
                })

        return candidates

    def _mutate_profile(
        self,
        current_profile: dict,
        train_sessions: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
        performance_breakdown: str | None = None,
        previous_f1: float | None = None,
    ) -> dict | None:
        """Mutate a profile using profile_refinement_prompt with reflective feedback."""
        if not self.refinement_prompt:
            logger.warning("No refinement prompt available, skipping mutation")
            return None

        # Build a text summary of training observations
        training_summary = self._build_training_summary(train_sessions, pdf_paths_dict, max_papers)

        # Use real breakdown or placeholder
        if not performance_breakdown:
            performance_breakdown = "No previous evaluation data available for this profile."
        prev_f1_str = f"{previous_f1:.3f}" if previous_f1 is not None else "N/A"

        prompt = self.refinement_prompt.format(
            current_profile=json.dumps(current_profile, indent=2, ensure_ascii=False),
            training_examples=training_summary,
            f1=previous_f1 or 0.0,
            total_val_days=0,
            previous_f1=prev_f1_str,
            performance_breakdown=performance_breakdown,
        )

        if self.debug:
            print(f"\n{'─'*70}")
            print("  [DEBUG] MUTATION/REFINEMENT PROMPT")
            print(f"{'─'*70}")
            print(f"  previous_f1: {prev_f1_str}")
            print(f"  breakdown length: {len(performance_breakdown)} chars")
            print(f"  training_summary length: {len(training_summary)} chars")
            print(f"  Full prompt ({len(prompt)} chars):")
            print(prompt)
            print(f"{'─'*70}\n")

        self._dump_payload("mutation", {
            "current_profile": current_profile,
            "training_summary": training_summary,
            "previous_f1": prev_f1_str,
            "performance_breakdown": performance_breakdown,
            "full_prompt": prompt,
        })

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            result = self.extractor._parse_json_response(response.text)
            if self.debug:
                print(f"  [DEBUG] MUTATION RESPONSE ({len(response.text)} chars):")
                print(response.text[:3000])
                print()
            logger.info("Mutation produced new profile (gen +1)")
            return result
        except Exception as e:
            logger.error("Profile mutation failed: %s", e)
            return None

    def _build_training_summary(
        self,
        training_data: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
    ) -> str:
        """Build a text summary of training data for the refinement prompt."""
        parts = []
        paper_count = 0
        for session in training_data:
            if paper_count >= max_papers:
                break
            day = session.get("day", "unknown")
            candidates = session.get("candidates", [])
            positives = [c for c in candidates if c.get("label") == 1]
            negatives = [c for c in candidates if c.get("label") == 0]

            parts.append(f"\n=== Day: {day} ===")
            if positives:
                parts.append("LIKED papers: " + ", ".join(
                    f"{p['paper_id']} ({p.get('title', 'N/A')})" for p in positives
                ))
            if negatives:
                parts.append("NOT LIKED papers: " + ", ".join(
                    f"{n['paper_id']} ({n.get('title', 'N/A')})" for n in negatives
                ))
            paper_count += len(candidates)

        return "\n".join(parts)

    def _evaluate_all(
        self,
        candidates: list[dict],
        val_sessions: list[dict],
        pdf_paths_dict: dict[str, str],
        max_val_days: int,
    ) -> list[dict]:
        """Evaluate all candidates on validation data."""
        # Skip candidates with default/fallback profiles (extraction failures)
        default_persona = self.extractor._default_profile().get("persona_definition", "")
        for candidate in candidates:
            profile = candidate.get("profile_json", {})
            if profile.get("persona_definition") == default_persona:
                logger.warning(
                    "Skipping evaluation of candidate with fallback profile (gen %d)",
                    candidate.get("generation", 0),
                )
                candidate["precision_val"] = 0.0
                candidate["recall_val"] = 0.0
                candidate["f1_val"] = 0.0
                candidate["val_days_count"] = 0
                continue
            result = self.evaluator.evaluate(
                candidate["profile_json"],
                val_sessions,
                pdf_paths_dict,
                max_val_days,
            )
            candidate["precision_val"] = result["precision"]
            candidate["recall_val"] = result["recall"]
            candidate["f1_val"] = result["f1"]
            candidate["val_days_count"] = result["val_days_count"]
            candidate["breakdown_str"] = result.get("breakdown_str", "")
            logger.info(
                f"📊 Candidate (gen {candidate.get('generation', 0)}): P={result['precision']:.3f} R={result['recall']:.3f} F1={result['f1']:.3f} ({result['val_days_count']} days)"
            )
            self._dump_payload("evaluation", {
                "id": candidate.get("id"),
                "generation": candidate.get("generation", 0),
                "parent_id": candidate.get("parent_id"),
                "precision": result["precision"],
                "recall": result["recall"],
                "f1": result["f1"],
                "val_days_count": result["val_days_count"],
                "breakdown_str": result.get("breakdown_str", ""),
            })
        return candidates

    def _prune_pool(self, candidates: list[dict]) -> list[dict]:
        """Prune candidates to pool_size. Keep Pareto front members first, then by F1."""
        if len(candidates) <= self.pool_size:
            return candidates

        # Separate Pareto front from the rest
        front = ParetoFront.compute(candidates)
        front_ids = {id(c) for c in front}

        non_front = [c for c in candidates if id(c) not in front_ids]
        non_front.sort(key=lambda c: c.get("f1_val") or 0.0, reverse=True)

        # Keep all Pareto members (up to pool_size), fill with best F1 from rest
        remaining_slots = self.pool_size - len(front)
        if remaining_slots > 0:
            result = front + non_front[:remaining_slots]
        else:
            # Too many Pareto members — keep best F1
            result = sorted(front, key=lambda c: c.get("f1_val") or 0.0, reverse=True)[
                : self.pool_size
            ]

        return result


def _get_gemini_key() -> str:
    """Get Gemini API key from environment."""
    import os

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY environment variable is not set")
    return key
