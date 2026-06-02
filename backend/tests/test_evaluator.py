"""EDD tests — evaluate pipeline quality against rubrics.

These tests verify that the evaluator correctly scores pipeline
quality. Unlike TDD tests that check code correctness, EDD tests
check system quality against real-world criteria.
"""

import pytest


class TestCompressionRubric:
    def test_healthy_compression(self):
        from app.analysis.evaluator import score_compression
        result = score_compression(
            compression_ratio=80.0, dedup_rate=0.35,
            suppress_rate=0.15, unique_finding_types=5,
        )
        assert result["score"] == "healthy"

    def test_warning_compression(self):
        from app.analysis.evaluator import score_compression
        result = score_compression(
            compression_ratio=25.0, dedup_rate=0.15,
            suppress_rate=0.08, unique_finding_types=2,
        )
        assert result["score"] == "warning"

    def test_failing_compression(self):
        from app.analysis.evaluator import score_compression
        result = score_compression(
            compression_ratio=5.0, dedup_rate=0.05,
            suppress_rate=0.01, unique_finding_types=1,
        )
        assert result["score"] == "failing"

    def test_over_suppression_is_warning(self):
        from app.analysis.evaluator import score_compression
        result = score_compression(
            compression_ratio=100.0, dedup_rate=0.5,
            suppress_rate=0.50, unique_finding_types=5,
        )
        assert result["score"] in ("warning", "failing")


class TestClassificationRubric:
    def test_healthy_classification(self):
        from app.analysis.evaluator import score_classification
        result = score_classification(
            json_compliance_rate=0.95, taxonomy_match_rate=0.90,
            inconsistent_names_rate=0.02, unclassified_rate=0.05,
        )
        assert result["score"] == "healthy"

    def test_poor_json_compliance(self):
        from app.analysis.evaluator import score_classification
        result = score_classification(
            json_compliance_rate=0.55, taxonomy_match_rate=0.40,
            inconsistent_names_rate=0.25, unclassified_rate=0.35,
        )
        assert result["score"] == "failing"


class TestInferenceRubric:
    def test_healthy_inference(self):
        from app.analysis.evaluator import score_inference
        result = score_inference(
            error_rate=0.03, avg_rca_tokens=600,
            avg_micro_tokens=100, unique_root_causes=8,
        )
        assert result["score"] == "healthy"

    def test_high_error_rate(self):
        from app.analysis.evaluator import score_inference
        result = score_inference(
            error_rate=0.25, avg_rca_tokens=600,
            avg_micro_tokens=100, unique_root_causes=8,
        )
        assert result["score"] in ("warning", "failing")


class TestCoverageRubric:
    def test_healthy_coverage(self):
        from app.analysis.evaluator import score_coverage
        result = score_coverage(
            namespaces_monitored=34, active_agents=10,
            signal_type_diversity=18, critical_signals_today=3,
        )
        assert result["score"] == "healthy"

    def test_low_coverage(self):
        from app.analysis.evaluator import score_coverage
        result = score_coverage(
            namespaces_monitored=5, active_agents=2,
            signal_type_diversity=3, critical_signals_today=0,
        )
        assert result["score"] in ("warning", "failing")


class TestSafetyRubric:
    def test_healthy_safety(self):
        from app.analysis.evaluator import score_safety
        result = score_safety(
            new_types_suppressed=0, cross_resource_dedup=0,
            critical_deduped=0,
        )
        assert result["score"] == "healthy"

    def test_safety_violation(self):
        from app.analysis.evaluator import score_safety
        result = score_safety(
            new_types_suppressed=2, cross_resource_dedup=1,
            critical_deduped=0,
        )
        assert result["score"] == "failing"


class TestOverallEvaluation:
    def test_evaluate_returns_all_rubrics(self):
        from app.analysis.evaluator import evaluate_pipeline
        result = evaluate_pipeline(
            cluster_id="test",
            compression_ratio=50.0, dedup_rate=0.3, suppress_rate=0.15,
            unique_finding_types=3, json_compliance_rate=0.85,
            taxonomy_match_rate=0.80, inconsistent_names_rate=0.05,
            unclassified_rate=0.10, error_rate=0.05, avg_rca_tokens=500,
            avg_micro_tokens=100, unique_root_causes=6,
            namespaces_monitored=30, active_agents=5,
            signal_type_diversity=15, critical_signals_today=2,
            new_types_suppressed=0, cross_resource_dedup=0, critical_deduped=0,
        )
        assert "rubrics" in result
        assert len(result["rubrics"]) == 5
        assert "overall" in result
        assert result["overall"] in ("healthy", "warning", "failing")


class TestRubricConfig:
    def test_defaults_match_hardcoded(self):
        from app.analysis.evaluator import RubricConfig, DEFAULT_CONFIG
        cfg = RubricConfig()
        assert cfg.compression_ratio_healthy == 50.0
        assert cfg.compression_ratio_warning == 10.0
        assert cfg.error_rate_healthy == 0.05
        assert cfg is not DEFAULT_CONFIG
        assert cfg.compression_ratio_healthy == DEFAULT_CONFIG.compression_ratio_healthy

    def test_overrides_are_independent(self):
        from app.analysis.evaluator import RubricConfig
        custom = RubricConfig(compression_ratio_healthy=20.0)
        default = RubricConfig()
        assert custom.compression_ratio_healthy == 20.0
        assert default.compression_ratio_healthy == 50.0


class TestRubricHistory:
    def _make_evaluation(self, overall="healthy", rubric_scores=None):
        return {
            "overall": overall,
            "rubrics": {
                "compression_quality": {"score": rubric_scores.get("compression_quality", overall) if rubric_scores else overall},
                "classification_accuracy": {"score": rubric_scores.get("classification_accuracy", overall) if rubric_scores else overall},
                "inference_value": {"score": rubric_scores.get("inference_value", overall) if rubric_scores else overall},
                "signal_coverage": {"score": rubric_scores.get("signal_coverage", overall) if rubric_scores else overall},
                "tuning_safety": {"score": rubric_scores.get("tuning_safety", overall) if rubric_scores else overall},
            },
        }

    def test_records_evaluation(self):
        from app.analysis.rubric_history import RubricHistory
        h = RubricHistory()
        h.record("test-cluster", self._make_evaluation("healthy"))
        entries = h.get_history("test-cluster")
        assert len(entries) == 1
        assert entries[0]["overall"] == "healthy"

    def test_trend_detects_improvement(self):
        from app.analysis.rubric_history import RubricHistory
        h = RubricHistory()
        for _ in range(3):
            h.record("trend-test", self._make_evaluation("failing"))
        for _ in range(3):
            h.record("trend-test", self._make_evaluation("healthy"))
        trend = h.get_trend("trend-test")
        assert trend["overall"] == "improving"

    def test_trend_detects_degradation(self):
        from app.analysis.rubric_history import RubricHistory
        h = RubricHistory()
        for _ in range(3):
            h.record("degrade-test", self._make_evaluation("healthy"))
        for _ in range(3):
            h.record("degrade-test", self._make_evaluation("failing"))
        trend = h.get_trend("degrade-test")
        assert trend["overall"] == "degrading"

    def test_trend_stable_when_unchanged(self):
        from app.analysis.rubric_history import RubricHistory
        h = RubricHistory()
        for _ in range(6):
            h.record("stable-test", self._make_evaluation("warning"))
        trend = h.get_trend("stable-test")
        assert trend["overall"] == "stable"

    def test_insufficient_data(self):
        from app.analysis.rubric_history import RubricHistory
        h = RubricHistory()
        h.record("short", self._make_evaluation("healthy"))
        trend = h.get_trend("short")
        assert trend["overall"] == "insufficient_data"


class TestScenarioRubricIntegration:
    def test_scenario_checks_map_to_rubric_inputs(self):
        from app.testing.scenario_runner import _evaluate_scenario, Scenario
        scenario = Scenario(
            id="test", name="Test", namespace="deepfield-e2e",
            inject_type="synthetic_signal",
        )
        result = {
            "checks": [
                {"check": "incident_created", "passed": True},
                {"check": "severity_correct", "passed": True},
                {"check": "classification_correct", "passed": True},
                {"check": "has_signals", "passed": True},
                {"check": "rca_produced", "passed": True},
                {"check": "has_remediation", "passed": True},
            ],
            "incident": {"signal_count": 3},
        }
        evaluation = _evaluate_scenario(scenario, result)
        assert "rubrics" in evaluation
        assert evaluation["overall"] in ("healthy", "warning", "failing")
