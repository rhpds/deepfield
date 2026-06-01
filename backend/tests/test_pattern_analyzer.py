"""Tests for the pattern analyzer — generates tuning proposals from signal data."""

import pytest


class TestPatternAnalyzer:
    def test_detect_noisy_namespace(self):
        from app.analysis.pattern_analyzer import detect_noisy_namespaces
        signal_counts = {"rh-ace-aiops": 5000, "stargate": 50, "deepfield": 30}
        suppressed_counts = {"rh-ace-aiops": 4900, "stargate": 5, "deepfield": 2}
        proposals = detect_noisy_namespaces(signal_counts, suppressed_counts, cluster_id="infra01")
        assert len(proposals) >= 1
        noisy = [p for p in proposals if p["category"] == "noise_resolution"]
        assert len(noisy) >= 1
        assert noisy[0]["evidence"]["namespace"] == "rh-ace-aiops"

    def test_no_proposal_for_clean_namespace(self):
        from app.analysis.pattern_analyzer import detect_noisy_namespaces
        signal_counts = {"clean-ns": 100}
        suppressed_counts = {"clean-ns": 5}
        proposals = detect_noisy_namespaces(signal_counts, suppressed_counts, cluster_id="test")
        assert len(proposals) == 0

    def test_detect_dedup_window_needed(self):
        from app.analysis.pattern_analyzer import detect_dedup_adjustments
        type_counts = {"event_failedscheduling": 10000, "pod_crashloop": 50}
        type_deduped = {"event_failedscheduling": 9500, "pod_crashloop": 3}
        proposals = detect_dedup_adjustments(type_counts, type_deduped, cluster_id="infra01")
        scheduling = [p for p in proposals if "event_failedscheduling" in str(p.get("evidence", {}))]
        assert len(scheduling) >= 1

    def test_detect_model_issues(self):
        from app.analysis.pattern_analyzer import detect_model_issues
        model_stats = {
            "good_model": {"calls": 100, "errors": 2, "error_rate": 0.02, "avg_latency": 200},
            "bad_model": {"calls": 100, "errors": 30, "error_rate": 0.30, "avg_latency": 25000},
        }
        proposals = detect_model_issues(model_stats, cluster_id="infra01")
        bad = [p for p in proposals if "bad_model" in str(p.get("evidence", {}))]
        assert len(bad) >= 1
        assert bad[0]["category"] == "model_rotation"

    def test_no_proposal_for_healthy_model(self):
        from app.analysis.pattern_analyzer import detect_model_issues
        model_stats = {
            "good_model": {"calls": 100, "errors": 1, "error_rate": 0.01, "avg_latency": 200},
        }
        proposals = detect_model_issues(model_stats, cluster_id="test")
        assert len(proposals) == 0

    def test_run_analysis_returns_proposals(self):
        from app.analysis.pattern_analyzer import run_analysis
        result = run_analysis(
            cluster_id="test",
            signal_counts={"type_a": 100},
            suppressed_counts={},
            type_counts={"type_a": 100},
            type_deduped={"type_a": 5},
            namespace_counts={"ns-a": 100},
            namespace_suppressed={"ns-a": 10},
            model_stats={},
        )
        assert "proposals" in result
        assert isinstance(result["proposals"], list)


class TestTuningAPI:
    @pytest.fixture
    async def client(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_get_proposals_endpoint(self, client):
        resp = await client.get("/api/v1/tuning/proposals")
        assert resp.status_code == 200
        data = resp.json()
        assert "proposals" in data

    @pytest.mark.asyncio
    async def test_get_profile_endpoint(self, client):
        resp = await client.get("/api/v1/tuning/profile/test-cluster")
        assert resp.status_code == 200
        data = resp.json()
        assert "cluster_id" in data
