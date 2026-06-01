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
