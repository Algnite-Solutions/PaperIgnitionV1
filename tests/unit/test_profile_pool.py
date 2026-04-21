"""Unit tests for ProfilePoolOptimizer logic with mocked API calls.

Tests cover:
- ParetoFront selection
- PoolEvaluator weighted F1
- ProfilePoolOptimizer.run_optimization (init + evolve)
- Time-decay weighting
- Pool pruning
"""

from unittest.mock import MagicMock, patch

import json

import pytest

from core.profile_pool import ParetoFront, PoolEvaluator, ProfilePoolOptimizer, calculate_f1


# ---------------------------------------------------------------------------
# calculate_f1
# ---------------------------------------------------------------------------

class TestCalculateF1:
    def test_perfect_match(self):
        result = calculate_f1({"a", "b"}, {"a", "b"})
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert result["f1"] == 1.0

    def test_no_overlap(self):
        result = calculate_f1({"a"}, {"b"})
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0
        assert result["f1"] == 0.0

    def test_partial_overlap(self):
        result = calculate_f1({"a", "b", "c"}, {"a", "b"})
        assert result["precision"] == pytest.approx(2 / 3)
        assert result["recall"] == 1.0
        assert result["f1"] == pytest.approx(4 / 5)

    def test_empty_both(self):
        result = calculate_f1(set(), set())
        assert result["f1"] == 1.0

    def test_empty_predicted(self):
        result = calculate_f1(set(), {"a"})
        assert result["f1"] == 0.0

    def test_empty_actual(self):
        result = calculate_f1({"a"}, set())
        assert result["f1"] == 0.0


# ---------------------------------------------------------------------------
# ParetoFront
# ---------------------------------------------------------------------------

class TestParetoFront:
    def test_empty(self):
        assert ParetoFront.compute([]) == []

    def test_single(self):
        c = {"precision_val": 0.5, "recall_val": 0.5, "f1_val": 0.5}
        assert ParetoFront.compute([c]) == [c]

    def test_dominated_removed(self):
        c1 = {"precision_val": 0.5, "recall_val": 0.5, "f1_val": 0.5}
        c2 = {"precision_val": 0.8, "recall_val": 0.8, "f1_val": 0.8}
        result = ParetoFront.compute([c1, c2])
        assert c1 not in result
        assert c2 in result

    def test_nondominated_both_kept(self):
        c1 = {"precision_val": 0.9, "recall_val": 0.3, "f1_val": 0.45}
        c2 = {"precision_val": 0.3, "recall_val": 0.9, "f1_val": 0.45}
        result = ParetoFront.compute([c1, c2])
        assert len(result) == 2

    def test_select_active_picks_highest_f1(self):
        c1 = {"precision_val": 0.9, "recall_val": 0.3, "f1_val": 0.45, "generation": 0}
        c2 = {"precision_val": 0.3, "recall_val": 0.9, "f1_val": 0.45, "generation": 1}
        active = ParetoFront.select_active([c1, c2])
        assert active is c2  # tiebreak: newer generation

    def test_select_active_none_vals(self):
        c1 = {"precision_val": None, "recall_val": None, "f1_val": None, "generation": 0}
        result = ParetoFront.select_active([c1])
        assert result is c1


# ---------------------------------------------------------------------------
# PoolEvaluator
# ---------------------------------------------------------------------------

def _make_sessions(day_data: list[tuple[str, list[tuple[str, int]]]]) -> list[dict]:
    """Helper: build session dicts from [(day, [(paper_id, label), ...])]"""
    sessions = []
    for day, papers in day_data:
        candidates = [
            {"paper_id": pid, "label": label, "title": f"Paper {pid}", "abstract": f"Abstract for {pid}"}
            for pid, label in papers
        ]
        sessions.append({"day": day, "candidates": candidates})
    return sessions


class TestPoolEvaluator:
    def _make_evaluator(self, rerank_results: dict[str, list[str]]):
        """Create evaluator with mocked reranker that returns preset results."""
        reranker = MagicMock()

        def mock_rerank(query, pdf_paths_dict, retrieve_ids, top_k, user_profile):
            # Return all predicted IDs from the preset
            day_pids = set(pdf_paths_dict.keys())
            for pid_list in rerank_results.values():
                matched = [p for p in pid_list if p in day_pids]
                if matched:
                    return matched, {}
            return [], {}

        reranker.rerank = MagicMock(side_effect=mock_rerank)
        return PoolEvaluator(reranker)

    def test_perfect_prediction(self):
        sessions = _make_sessions([
            ("2026-01-01", [("p1", 1), ("p2", 1), ("p3", 0)]),
        ])
        pdf_paths = {"p1": "/a.pdf", "p2": "/b.pdf", "p3": "/c.pdf"}
        evaluator = self._make_evaluator({"2026-01-01": ["p1", "p2"]})
        profile = {"persona_definition": "test"}

        result = evaluator.evaluate(profile, sessions, pdf_paths)
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert result["f1"] == 1.0

    def test_partial_prediction(self):
        sessions = _make_sessions([
            ("2026-01-01", [("p1", 1), ("p2", 1), ("p3", 0)]),
        ])
        pdf_paths = {"p1": "/a.pdf", "p2": "/b.pdf", "p3": "/c.pdf"}
        # Only predict p1 (miss p2) → precision=1.0, recall=0.5
        evaluator = self._make_evaluator({"2026-01-01": ["p1"]})
        profile = {"persona_definition": "test"}

        result = evaluator.evaluate(profile, sessions, pdf_paths)
        assert result["precision"] == 1.0
        assert result["recall"] == 0.5
        assert result["f1"] == pytest.approx(2 / 3)

    def test_fp_lowers_precision(self):
        sessions = _make_sessions([
            ("2026-01-01", [("p1", 1), ("p2", 0)]),
        ])
        pdf_paths = {"p1": "/a.pdf", "p2": "/b.pdf"}
        # Predict both → precision=0.5 (p2 is FP), recall=1.0
        evaluator = self._make_evaluator({"2026-01-01": ["p1", "p2"]})
        profile = {"persona_definition": "test"}

        result = evaluator.evaluate(profile, sessions, pdf_paths)
        assert result["precision"] == 0.5
        assert result["recall"] == 1.0

    def test_decay_weights_recent_more(self):
        sessions = _make_sessions([
            ("2026-01-01", [("p1", 1), ("p2", 0)]),  # old
            ("2026-01-02", [("p3", 1), ("p4", 0)]),  # recent
        ])
        pdf_paths = {"p1": "/a.pdf", "p2": "/b.pdf", "p3": "/c.pdf", "p4": "/d.pdf"}
        # Day 1: predict p1 → P=1.0, R=1.0
        # Day 2: predict p3,p4 → P=0.5, R=1.0
        evaluator = self._make_evaluator({"2026-01-01": ["p1"], "2026-01-02": ["p3", "p4"]})
        profile = {"persona_definition": "test"}

        # No decay
        result_uniform = evaluator.evaluate(profile, sessions, pdf_paths, decay=None)
        # With decay=0.5: recent weighted more
        result_decay = evaluator.evaluate(profile, sessions, pdf_paths, decay=0.5)

        # Uniform: avg P = (1.0 + 0.5) / 2 = 0.75
        assert result_uniform["precision"] == 0.75
        # Decay=0.5: weights = [0.5, 1.0], weighted P = (1.0*0.5 + 0.5*1.0) / 1.5 = 0.667
        assert result_decay["precision"] == pytest.approx(1.0 / 1.5)

    def test_breakdown_contains_tp_fp_fn(self):
        sessions = _make_sessions([
            ("2026-01-01", [("p1", 1), ("p2", 1), ("p3", 0)]),
        ])
        pdf_paths = {"p1": "/a.pdf", "p2": "/b.pdf", "p3": "/c.pdf"}
        # Predict p1,p3 → TP=p1, FP=p3, FN=p2
        evaluator = self._make_evaluator({"2026-01-01": ["p1", "p3"]})
        profile = {"persona_definition": "test"}

        result = evaluator.evaluate(profile, sessions, pdf_paths)
        assert "p1" in result["tp_paper_ids"]
        assert "p3" in result["fp_paper_ids"]
        assert "p2" in result["fn_paper_ids"]
        assert "True Positives" in result["breakdown_str"]
        assert "False Positives" in result["breakdown_str"]
        assert "False Negatives" in result["breakdown_str"]

    def test_no_pdfs_skips_day(self):
        sessions = _make_sessions([
            ("2026-01-01", [("p1", 1)]),
        ])
        pdf_paths = {}  # no PDFs
        evaluator = self._make_evaluator({})
        result = evaluator.evaluate({}, sessions, pdf_paths)
        assert result["f1"] == 0.0
        assert result["val_days_count"] == 0


# ---------------------------------------------------------------------------
# ProfilePoolOptimizer (mocked API)
# ---------------------------------------------------------------------------

def _mock_optimizer():
    """Create optimizer with mocked Gemini client (no real API calls)."""
    with patch("core.profile_pool.genai.Client"), \
         patch("core.profile_pool._get_gemini_key", return_value="fake-key"):
        extractor = MagicMock()
        extractor._default_profile.return_value = {
            "persona_definition": "Default profile.",
            "negative_constraints": [],
            "ranking_heuristics": [],
        }
        evaluator = MagicMock()

        optimizer = ProfilePoolOptimizer(
            extractor=extractor,
            evaluator=evaluator,
            pool_size=5,
            max_mutations=2,
            debug=False,
        )
    return optimizer, extractor, evaluator


class TestProfilePoolOptimizerInit:
    def test_first_boost_creates_3_candidates(self):
        optimizer, extractor, evaluator = _mock_optimizer()

        # Mock extraction: return a profile for each variant call
        mock_profile = {
            "persona_definition": "Test persona",
            "negative_constraints": ["c1"],
            "ranking_heuristics": ["h1"],
        }
        extractor._build_pdf_contents.return_value = []
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_profile)
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=100, total_token_count=200
        )
        optimizer.client.models.generate_content.return_value = mock_response

        # Mock evaluation
        evaluator.evaluate.return_value = {
            "precision": 0.5, "recall": 0.8, "f1": 0.6,
            "val_days_count": 2, "breakdown_str": "test",
        }

        train = _make_sessions([("2026-01-01", [("p1", 1)])])
        val = _make_sessions([("2026-01-02", [("p2", 1)])])
        pdf_paths = {"p1": "/a.pdf", "p2": "/b.pdf"}

        result = optimizer.run_optimization(
            train_sessions=train,
            val_bins=val,
            pdf_paths_dict=pdf_paths,
            max_papers=10,
        )

        # 3 variants extracted
        assert len(result["pool"]) == 3
        assert result["active_profile"] is not None
        # Pareto selected one as active
        active_count = sum(1 for c in result["pool"] if c.get("is_active"))
        assert active_count == 1

    def test_empty_train_returns_empty(self):
        optimizer, _, _ = _mock_optimizer()
        result = optimizer.run_optimization(
            train_sessions=[],
            val_bins=[],
            pdf_paths_dict={},
        )
        assert result["pool"] == []
        assert result["active_profile"] is None


class TestProfilePoolOptimizerEvolve:
    def test_subsequent_boost_mutates_top2(self):
        optimizer, extractor, evaluator = _mock_optimizer()

        # Existing pool with scores
        existing_pool = [
            {
                "profile_json": {"persona_definition": "P1"},
                "generation": 0,
                "f1_val": 0.8,
                "mutation_note": "init",
            },
            {
                "profile_json": {"persona_definition": "P2"},
                "generation": 0,
                "f1_val": 0.5,
                "mutation_note": "init",
            },
        ]

        # Mock mutation response
        mutated_profile = {
            "persona_definition": "Mutated",
            "negative_constraints": [],
            "ranking_heuristics": [],
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps(mutated_profile)
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=50, total_token_count=100
        )
        optimizer.client.models.generate_content.return_value = mock_response
        extractor._parse_json_response.return_value = mutated_profile

        # Mock evaluation
        evaluator.evaluate.return_value = {
            "precision": 0.6, "recall": 0.7, "f1": 0.65,
            "val_days_count": 1, "breakdown_str": "test",
        }

        train = _make_sessions([("2026-01-01", [("p1", 1)])])
        val = _make_sessions([("2026-01-02", [("p2", 1)])])
        pdf_paths = {"p1": "/a.pdf", "p2": "/b.pdf"}

        result = optimizer.run_optimization(
            train_sessions=train,
            val_bins=val,
            pdf_paths_dict=pdf_paths,
            existing_pool=existing_pool,
            max_papers=10,
            performance_breakdown="TP/FP/FN breakdown",
            previous_f1=0.8,
        )

        # 2 existing + 2 mutated = 4 candidates
        assert len(result["pool"]) == 4
        # Mutated candidates should be generation 1
        gens = [c["generation"] for c in result["pool"]]
        assert 1 in gens


class TestProfilePoolOptimizerPrune:
    def test_pool_pruned_to_size(self):
        optimizer, extractor, evaluator = _mock_optimizer()

        # Return mock profile
        mock_profile = {
            "persona_definition": "Test",
            "negative_constraints": [],
            "ranking_heuristics": [],
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_profile)
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=100, total_token_count=200
        )
        optimizer.client.models.generate_content.return_value = mock_response

        # Evaluate gives different F1s
        call_count = [0]
        def mock_evaluate(profile, val_days, pdf_paths, max_val, **kwargs):
            call_count[0] += 1
            return {
                "precision": 0.5 + call_count[0] * 0.05,
                "recall": 0.5,
                "f1": 0.5 + call_count[0] * 0.05,
                "val_days_count": 1,
                "breakdown_str": "",
            }
        evaluator.evaluate.side_effect = mock_evaluate

        # Use pool_size=2 to force pruning
        optimizer.pool_size = 2
        train = _make_sessions([("2026-01-01", [("p1", 1)])])
        val = _make_sessions([("2026-01-02", [("p2", 1)])])

        result = optimizer.run_optimization(
            train_sessions=train,
            val_bins=val,
            pdf_paths_dict={"p1": "/a.pdf", "p2": "/b.pdf"},
            max_papers=10,
        )

        assert len(result["pool"]) <= 2


class TestPoolDynamicEvolution:
    """Test the full feedback loop: eval scores drive mutation selection + Pareto."""

    def _setup_optimizer(self):
        with patch("core.profile_pool.genai.Client"), \
             patch("core.profile_pool._get_gemini_key", return_value="fake-key"):
            extractor = MagicMock()
            extractor._default_profile.return_value = {
                "persona_definition": "Default profile.",
                "negative_constraints": [],
                "ranking_heuristics": [],
            }
            evaluator = MagicMock()
            optimizer = ProfilePoolOptimizer(
                extractor=extractor,
                evaluator=evaluator,
                pool_size=5,
                max_mutations=2,
                debug=False,
            )
        return optimizer, extractor, evaluator

    def test_top_f1_candidates_are_selected_for_mutation(self):
        """_evolve_pool should mutate the top-2 candidates by f1_val."""
        optimizer, extractor, evaluator = self._setup_optimizer()

        # Pool with 3 candidates at different F1 scores
        existing_pool = [
            {"profile_json": {"persona_definition": "Best"}, "generation": 0,
             "f1_val": 0.9, "mutation_note": "init"},
            {"profile_json": {"persona_definition": "Mid"}, "generation": 0,
             "f1_val": 0.5, "mutation_note": "init"},
            {"profile_json": {"persona_definition": "Worst"}, "generation": 0,
             "f1_val": 0.1, "mutation_note": "init"},
        ]

        # Track which profiles get sent for mutation
        mutated_profiles = []
        original_mutate = optimizer._mutate_profile

        def track_mutate(current_profile, *args, **kwargs):
            mutated_profiles.append(current_profile["persona_definition"])
            return {"persona_definition": f"Mutated-{current_profile['persona_definition']}",
                    "negative_constraints": [], "ranking_heuristics": []}

        optimizer._mutate_profile = track_mutate

        # All candidates get same eval score (so mutation selection matters)
        evaluator.evaluate.return_value = {
            "precision": 0.5, "recall": 0.5, "f1": 0.5,
            "val_days_count": 1, "breakdown_str": "",
        }

        train = _make_sessions([("2026-01-01", [("p1", 1)])])
        val = _make_sessions([("2026-01-02", [("p2", 1)])])

        result = optimizer.run_optimization(
            train_sessions=train,
            val_bins=val,
            pdf_paths_dict={"p1": "/a.pdf", "p2": "/b.pdf"},
            existing_pool=existing_pool,
            max_papers=10,
        )

        # Top-2 by F1 should be mutated: "Best" (0.9) and "Mid" (0.5)
        assert len(mutated_profiles) == 2
        assert "Best" in mutated_profiles
        assert "Mid" in mutated_profiles
        assert "Worst" not in mutated_profiles

    def test_pareto_picks_highest_f1_after_eval(self):
        """After evaluation, Pareto should select the candidate with highest F1."""
        optimizer, extractor, evaluator = self._setup_optimizer()

        profiles = [
            {"persona_definition": "A", "negative_constraints": [], "ranking_heuristics": []},
            {"persona_definition": "B", "negative_constraints": [], "ranking_heuristics": []},
            {"persona_definition": "C", "negative_constraints": [], "ranking_heuristics": []},
        ]
        # Return valid JSON so _parse_json_response succeeds on first try (no retry)
        mock_response = MagicMock()
        mock_response.text = json.dumps(profiles[0])
        mock_response.usage_metadata = MagicMock(prompt_token_count=0, total_token_count=0)
        optimizer.client.models.generate_content.return_value = mock_response
        extractor._parse_json_response.side_effect = profiles
        extractor._build_pdf_contents.return_value = []

        # Give different F1 scores per candidate
        eval_count = [0]
        def mock_evaluate(profile, *args, **kwargs):
            eval_count[0] += 1
            f1 = 0.3 if profile["persona_definition"] == "A" else 0.8
            return {"precision": f1, "recall": f1, "f1": f1,
                    "val_days_count": 1, "breakdown_str": ""}
        evaluator.evaluate.side_effect = mock_evaluate

        train = _make_sessions([("2026-01-01", [("p1", 1)])])
        val = _make_sessions([("2026-01-02", [("p2", 1)])])

        result = optimizer.run_optimization(
            train_sessions=train,
            val_bins=val,
            pdf_paths_dict={"p1": "/a.pdf", "p2": "/b.pdf"},
            max_papers=10,
        )

        # B has F1=0.8, should be active
        assert result["active_profile"]["persona_definition"] == "B"

    def test_two_boost_cycle_feedback(self):
        """Full 2-boost cycle: init → eval → mutate → eval → Pareto selects better."""
        optimizer, extractor, evaluator = self._setup_optimizer()

        init_profiles = [
            {"persona_definition": f"Init-{i}", "negative_constraints": [], "ranking_heuristics": []}
            for i in range(3)
        ]
        mutated_profile = {
            "persona_definition": "Mutated-0",
            "negative_constraints": ["no RL"],
            "ranking_heuristics": ["prefer compression"],
        }

        mock_response = MagicMock()
        mock_response.text = "unused"
        mock_response.usage_metadata = MagicMock(prompt_token_count=0, total_token_count=0)
        optimizer.client.models.generate_content.return_value = mock_response
        extractor._parse_json_response.side_effect = init_profiles + [mutated_profile, mutated_profile]
        extractor._build_pdf_contents.return_value = []

        # Boost 1: all 3 variants get F1=0.3
        # Boost 2: originals get F1=0.3, mutated gets F1=0.7
        eval_results = iter([
            {"precision": 0.3, "recall": 0.3, "f1": 0.3, "val_days_count": 1, "breakdown_str": ""},
            {"precision": 0.3, "recall": 0.3, "f1": 0.3, "val_days_count": 1, "breakdown_str": ""},
            {"precision": 0.3, "recall": 0.3, "f1": 0.3, "val_days_count": 1, "breakdown_str": ""},
            # Boost 2: 3 originals + 2 mutated
            {"precision": 0.3, "recall": 0.3, "f1": 0.3, "val_days_count": 1, "breakdown_str": ""},
            {"precision": 0.3, "recall": 0.3, "f1": 0.3, "val_days_count": 1, "breakdown_str": ""},
            {"precision": 0.3, "recall": 0.3, "f1": 0.3, "val_days_count": 1, "breakdown_str": ""},
            {"precision": 0.7, "recall": 0.7, "f1": 0.7, "val_days_count": 1, "breakdown_str": "TP/FP"},
            {"precision": 0.7, "recall": 0.7, "f1": 0.7, "val_days_count": 1, "breakdown_str": "TP/FP"},
        ])
        evaluator.evaluate.side_effect = lambda *a, **k: next(eval_results)

        train = _make_sessions([("2026-01-01", [("p1", 1)])])
        val = _make_sessions([("2026-01-02", [("p2", 1)])])

        # Boost 1: init
        result1 = optimizer.run_optimization(
            train_sessions=train, val_bins=val,
            pdf_paths_dict={"p1": "/a.pdf", "p2": "/b.pdf"}, max_papers=10,
        )
        assert len(result1["pool"]) == 3
        assert result1["active_profile"]["persona_definition"].startswith("Init-")

        # Boost 2: evolve with feedback
        result2 = optimizer.run_optimization(
            train_sessions=train, val_bins=val,
            pdf_paths_dict={"p1": "/a.pdf", "p2": "/b.pdf"}, max_papers=10,
            existing_pool=result1["pool"],
            performance_breakdown="TP/FP breakdown from boost 1",
            previous_f1=0.3,
        )

        # Mutated profile (F1=0.7) should win over originals (F1=0.3)
        assert result2["active_profile"]["persona_definition"] == "Mutated-0"
        # Pool should have 5 candidates (3 original + 2 mutated)
        assert len(result2["pool"]) == 5

    def test_mutation_receives_breakdown_and_f1(self):
        """Mutation should receive the parent's own breakdown_str and f1_val."""
        optimizer, extractor, evaluator = self._setup_optimizer()

        received_kwargs = {}

        def capture_mutate(profile, train_sessions, pdf_paths_dict, max_papers,
                          performance_breakdown=None, previous_f1=None):
            received_kwargs["performance_breakdown"] = performance_breakdown
            received_kwargs["previous_f1"] = previous_f1
            return {"persona_definition": "Mutated", "negative_constraints": [],
                    "ranking_heuristics": []}
        optimizer._mutate_profile = capture_mutate

        evaluator.evaluate.return_value = {
            "precision": 0.6, "recall": 0.8, "f1": 0.667,
            "val_days_count": 2, "breakdown_str": "",
        }

        # Parent has its own breakdown_str and f1_val from previous evaluation
        existing_pool = [
            {"profile_json": {"persona_definition": "P1"}, "generation": 0,
             "f1_val": 0.5, "mutation_note": "init",
             "breakdown_str": "### Session: 2026-01-02\nTP: p2\nFP: p3\nFN: p4"},
        ]

        train = _make_sessions([("2026-01-01", [("p1", 1)])])
        val = _make_sessions([("2026-01-02", [("p2", 1)])])

        optimizer.run_optimization(
            train_sessions=train, val_bins=val,
            pdf_paths_dict={"p1": "/a.pdf", "p2": "/b.pdf"},
            existing_pool=existing_pool,
            max_papers=10,
        )

        # Should use the parent's own breakdown_str, not a global one
        assert received_kwargs["performance_breakdown"] == "### Session: 2026-01-02\nTP: p2\nFP: p3\nFN: p4"
        assert received_kwargs["previous_f1"] == 0.5
