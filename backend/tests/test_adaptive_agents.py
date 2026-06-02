"""Tests for adaptive nano-agent behavior with cluster profiles."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4, UUID

from app.domain.models import NormalizedSignal, FilterDecision
from app.session.cluster_profile import ClusterProfile
from app.nanoagents import dedupe, transient_suppressor

_FIXED_CLUSTER = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def _reset_agent_state():
    dedupe.reset_state()
    transient_suppressor.reset_state()
    yield
    dedupe.reset_state()
    transient_suppressor.reset_state()


def _make_signal(signal_type: str, namespace: str = "test-ns", cluster: str = "infra01",
                 resource_name: str = "pod-1", ts_offset: float = 0) -> NormalizedSignal:
    return NormalizedSignal(
        signal_id=uuid4(),
        cluster_id=_FIXED_CLUSTER,
        namespace=namespace,
        resource_kind="Pod",
        resource_name=resource_name,
        signal_type=signal_type,
        severity="medium",
        confidence=1.0,
        deterministic=True,
        labels={},
        evidence={},
        timestamp=datetime.fromtimestamp(1700000000 + ts_offset, tz=timezone.utc),
    )


class TestAdaptiveDedup:
    def test_default_window_without_profile(self):
        signals = [
            _make_signal("pod_crashloop", ts_offset=0),
            _make_signal("pod_crashloop", ts_offset=30),
        ]
        decisions = dedupe.filter(signals)
        assert len(decisions) == 1
        assert decisions[0].outcome == "dedupe"

    def test_custom_window_from_profile(self):
        profile = ClusterProfile(cluster_id="test", dedup_windows={"pod_crashloop": 10})
        signals = [
            _make_signal("pod_crashloop", ts_offset=0),
            _make_signal("pod_crashloop", ts_offset=15),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        assert len(decisions) == 0

    def test_wide_window_from_profile_catches_more(self):
        profile = ClusterProfile(cluster_id="test", dedup_windows={"event_failedscheduling": 600})
        signals = [
            _make_signal("event_failedscheduling", ts_offset=0),
            _make_signal("event_failedscheduling", ts_offset=120),
            _make_signal("event_failedscheduling", ts_offset=300),
            _make_signal("event_failedscheduling", ts_offset=500),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        assert len(decisions) == 3

    def test_different_types_different_windows(self):
        profile = ClusterProfile(cluster_id="test", dedup_windows={
            "event_failedscheduling": 600,
        })
        signals = [
            _make_signal("event_failedscheduling", resource_name="pod-a", ts_offset=0),
            _make_signal("event_failedscheduling", resource_name="pod-a", ts_offset=120),
            _make_signal("pod_crashloop", resource_name="pod-b", ts_offset=0),
            _make_signal("pod_crashloop", resource_name="pod-b", ts_offset=120),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        deduped_types = [d.evidence.get("duplicate_of_key", "").split(":")[-1] for d in decisions]
        assert "event_failedscheduling" in deduped_types
        assert "pod_crashloop" not in deduped_types


class TestAdaptiveSuppressor:
    def test_dampening_with_default_threshold(self):
        signals = [_make_signal("event_backoff", ts_offset=i) for i in range(15)]
        decisions = transient_suppressor.filter(signals)
        suppressed = [d for d in decisions if d.reason_code == "namespace_dampened"]
        assert len(suppressed) == 5

    def test_dampening_with_profile_threshold(self):
        profile = ClusterProfile(cluster_id="test", namespace_dampen_thresholds={"test-ns": 5})
        signals = [_make_signal("event_backoff", ts_offset=i) for i in range(15)]
        decisions = transient_suppressor.filter(signals, cluster_profile=profile)
        suppressed = [d for d in decisions if d.reason_code == "namespace_dampened"]
        assert len(suppressed) == 10

    def test_transient_suppression_still_works(self):
        signals = [
            _make_signal("pod_pending", ts_offset=0),
            _make_signal("pod_pending", ts_offset=30),
        ]
        decisions = transient_suppressor.filter(signals)
        transients = [d for d in decisions if d.reason_code == "transient_within_window"]
        assert len(transients) == 1


class TestPipelineWithProfile:
    def test_pipeline_accepts_profile(self):
        from app.nanoagents.pipeline import run_pipeline
        profile = ClusterProfile(cluster_id="test", dedup_windows={"event_failedscheduling": 600})
        signals = [
            _make_signal("event_failedscheduling", ts_offset=0),
            _make_signal("event_failedscheduling", ts_offset=120),
        ]
        result = run_pipeline(signals, cluster_profile=profile)
        assert result["deduped_count"] == 1

    def test_pipeline_works_without_profile(self):
        from app.nanoagents.pipeline import run_pipeline
        signals = [_make_signal("pod_crashloop")]
        result = run_pipeline(signals)
        assert result["total_signals"] == 1
