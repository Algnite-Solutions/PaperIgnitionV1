"""GEPA-inspired profile pool optimization for personalized paper recommendations.

Maintains a pool of candidate user profiles, evaluates them on held-out validation
data (rolling window), and evolves them via reflective mutation using Pareto-front
selection across precision and recall.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from google import genai

from .rerankers import GeminiProfileExtractor, GeminiRerankerPDF

logger = logging.getLogger(__name__)

# Variant prompt framings for initial pool diversity
_VARIANT_FRAMINGS = {
    "default": None,  # use the base profile_extraction_prompt as-is
    "methodology": (
        "\n\n**Special Focus:** Pay extra attention to METHODOLOGY preferences — "
        "what kinds of experimental setups, evaluation metrics, or analytical approaches "
        "does this researcher gravitate toward?"
    ),
    "topic_breadth": (
        "\n\n**Special Focus:** Pay extra attention to TOPIC BREADTH — "
        "does this researcher prefer deep work in a narrow niche, or cross-domain papers "
        "that connect different research areas?"
    ),
}


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
    ) -> dict:
        """
        Evaluate a profile on validation days.

        Args:
            profile: {persona_definition, negative_constraints, ranking_heuristics}
            val_days: [{day, candidates: [{paper_id, label}]}]
            pdf_paths_dict: paper_id → local PDF path
            max_val_days: max validation days to evaluate (cost control)

        Returns:
            {precision, recall, f1, val_days_count, per_day_breakdown}
        """
        sampled_days = val_days[:max_val_days]
        results = []

        for day_item in sampled_days:
            day_str = day_item["day"]
            candidates = day_item["candidates"]
            actual_positives = {c["paper_id"] for c in candidates if c.get("label") == 1}

            if not actual_positives:
                continue

            # Build PDF paths for this day's candidates
            day_pdf_paths = {
                c["paper_id"]: pdf_paths_dict[c["paper_id"]]
                for c in candidates
                if c["paper_id"] in pdf_paths_dict
            }

            if not day_pdf_paths:
                logger.warning("Day %s: no PDFs available, skipping", day_str)
                continue

            try:
                ranked, _ = self.reranker.rerank(
                    query="",
                    pdf_paths_dict=day_pdf_paths,
                    retrieve_ids=list(day_pdf_paths.keys()),
                    top_k=len(day_pdf_paths),
                    user_profile=profile,
                )
                predicted = set(ranked) if ranked else set()
            except Exception as e:
                logger.error("Error evaluating day %s: %s", day_str, e)
                predicted = set()

            metrics = calculate_f1(predicted, actual_positives)
            results.append(
                {
                    "day": day_str,
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "f1": metrics["f1"],
                    "num_candidates": len(candidates),
                    "num_actual": len(actual_positives),
                    "num_predicted": len(predicted),
                }
            )

        if not results:
            return {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "val_days_count": 0,
                "per_day_breakdown": [],
            }

        avg_precision = sum(r["precision"] for r in results) / len(results)
        avg_recall = sum(r["recall"] for r in results) / len(results)
        avg_f1 = sum(r["f1"] for r in results) / len(results)

        return {
            "precision": avg_precision,
            "recall": avg_recall,
            "f1": avg_f1,
            "val_days_count": len(results),
            "per_day_breakdown": results,
        }


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
    ):
        self.extractor = extractor
        self.evaluator = evaluator
        self.pool_size = pool_size
        self.max_mutations = max_mutations
        self.model_name = model_name

        api_key = _get_gemini_key()
        self.client = genai.Client(api_key=api_key)

        # Load refinement prompt
        prompt_path = Path(__file__).parent / "prompts" / "rerank_prompts.yaml"
        with open(prompt_path) as f:
            prompts = yaml.safe_load(f)
        self.refinement_prompt = prompts.get("profile_refinement_prompt", "")
        self.extraction_prompt = prompts.get("profile_extraction_prompt", "")

    def run_optimization(
        self,
        all_sessions: list[dict],
        pdf_paths_dict: dict[str, str],
        existing_pool: list[dict] | None = None,
        max_papers: int = 50,
        max_val_days: int = 7,
    ) -> dict:
        """
        Run the full optimization loop.

        Args:
            all_sessions: all sessions with liked papers, sorted chronologically
                [{day, candidates: [{paper_id, label, title, abstract}]}]
            pdf_paths_dict: paper_id → local PDF path
            existing_pool: existing pool entries from DB (may be empty/None)
            max_papers: max PDF pages for training
            max_val_days: max validation days to evaluate

        Returns:
            {pool: [...], active_profile: {...}, active_id: int|None}
        """
        # Split data: recent → train, older → val
        train_sessions, val_sessions = self._split_train_val(all_sessions, max_papers, max_val_days)

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
                existing_pool, train_sessions, pdf_paths_dict, max_papers
            )

        # Evaluate all candidates on validation data
        if val_sessions:
            logger.info("Evaluating %d candidates on %d validation days", len(candidates), len(val_sessions))
            candidates = self._evaluate_all(candidates, val_sessions, pdf_paths_dict, max_val_days)
        else:
            logger.warning("No validation sessions — skipping evaluation")

        # Compute Pareto front and prune
        active = ParetoFront.select_active(candidates)
        if active is None:
            # Fallback: pick the newest candidate
            active = candidates[-1] if candidates else None

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

        active_id = active.get("id") if active else None

        return {
            "pool": pool,
            "active_profile": active.get("profile_json") if active else None,
            "active_id": active_id,
        }

    def _split_train_val(
        self,
        all_sessions: list[dict],
        max_papers: int,
        max_val_days: int,
    ) -> tuple[list[dict], list[dict]]:
        """Split sessions: most recent → training (capped by max_papers),
        previous sessions with positives → validation (up to max_val_days)."""
        if not all_sessions:
            return [], []

        # Sessions are already sorted chronologically
        # Work backwards: count how many sessions fit in max_papers for training
        train_sessions = []
        paper_count = 0
        for session in reversed(all_sessions):
            n_papers = len(session.get("candidates", []))
            if paper_count + n_papers > max_papers:
                break
            train_sessions.insert(0, session)
            paper_count += n_papers

        # Validation = sessions immediately before the training window, up to max_val_days
        if train_sessions:
            train_start_idx = all_sessions.index(train_sessions[0])
        else:
            train_start_idx = len(all_sessions)

        # Take up to max_val_days sessions before training, but only those with positives
        val_sessions = []
        for session in reversed(all_sessions[:train_start_idx]):
            has_positives = any(c.get("label") == 1 for c in session.get("candidates", []))
            if has_positives:
                val_sessions.insert(0, session)
                if len(val_sessions) >= max_val_days:
                    break

        logger.info(
            "Split: %d train sessions (%d papers), %d val sessions",
            len(train_sessions),
            paper_count,
            len(val_sessions),
        )
        return train_sessions, val_sessions

    def _initialize_pool(
        self,
        train_sessions: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
    ) -> list[dict]:
        """First boost: extract 1 base profile + 2 variants."""
        candidates = []

        for variant_name, framing_suffix in _VARIANT_FRAMINGS.items():
            profile, usage = self._extract_with_framing(
                train_sessions, pdf_paths_dict, max_papers, framing_suffix
            )
            candidates.append({
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
                return self.extractor._default_profile(), {"input_tokens": 0, "total_tokens": 0}

    def _evolve_pool(
        self,
        existing_pool: list[dict],
        train_sessions: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
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
            })

        # Sort existing by previous F1 (if available) for mutation selection
        scored = [c for c in candidates if c.get("f1_val") is not None]
        if not scored:
            scored = candidates

        top_candidates = sorted(
            scored,
            key=lambda c: c.get("f1_val") or 0.0,
            reverse=True,
        )[:self.max_mutations]

        # Mutate top candidates via profile_refinement_prompt
        for parent in top_candidates:
            mutated_profile = self._mutate_profile(
                parent["profile_json"],
                train_sessions,
                pdf_paths_dict,
                max_papers,
            )
            if mutated_profile:
                candidates.append({
                    "profile_json": mutated_profile,
                    "generation": parent.get("generation", 0) + 1,
                    "parent_id": parent.get("id"),
                    "mutation_note": f"Reflective mutation from gen {parent.get('generation', 0)}",
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
    ) -> dict | None:
        """Mutate a profile using profile_refinement_prompt with reflective feedback."""
        if not self.refinement_prompt:
            logger.warning("No refinement prompt available, skipping mutation")
            return None

        # Build a text summary of training observations
        training_summary = self._build_training_summary(train_sessions, pdf_paths_dict, max_papers)

        # Build performance breakdown (placeholder — will be filled after evaluation)
        performance_breakdown = "First mutation cycle — no previous evaluation data available."

        prompt = self.refinement_prompt.format(
            current_profile=json.dumps(current_profile, indent=2, ensure_ascii=False),
            training_examples=training_summary,
            hit_at_1=0.0,
            hit_count=0,
            total_val_days=0,
            previous_hit_at_1="N/A",
            performance_breakdown=performance_breakdown,
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            result = self.extractor._parse_json_response(response.text)
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
            logger.info(
                "Candidate (gen %d): P=%.3f R=%.3f F1=%.3f (%d val days)",
                candidate.get("generation", 0),
                result["precision"],
                result["recall"],
                result["f1"],
                result["val_days_count"],
            )
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
