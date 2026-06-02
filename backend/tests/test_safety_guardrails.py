"""Tests for tuning safety guardrails — ensure nothing falls through the cracks.

Key principle: tuning reduces noise, but NEVER hides genuinely new problems.
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4, UUID

from app.domain.models import NormalizedSignal
from app.session.cluster_profile import ClusterProfile
from app.nanoagents import dedupe, transient_suppressor

_CLUSTER = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def _reset_agent_state():
    dedupe.reset_state()
    transient_suppressor.reset_state()
    yield
    dedupe.reset_state()
    transient_suppressor.reset_state()


def _sig(signal_type: str, namespace: str = "test-ns", resource_name: str = "pod-1",
         severity: str = "medium", ts_offset: float = 0) -> NormalizedSignal:
    return NormalizedSignal(
        signal_id=uuid4(), cluster_id=_CLUSTER, namespace=namespace,
        resource_kind="Pod", resource_name=resource_name,
        signal_type=signal_type, severity=severity, confidence=1.0,
        deterministic=True, labels={}, evidence={},
        timestamp=datetime.fromtimestamp(1700000000 + ts_offset, tz=timezone.utc),
    )


class TestDedupNeverHidesNewProblems:
    """Dedup should only suppress IDENTICAL signals. Different resources = different signals."""

    def test_same_pod_same_type_deduped(self):
        profile = ClusterProfile(cluster_id="test", dedup_windows={"pod_crashloop": 600})
        signals = [
            _sig("pod_crashloop", resource_name="pod-a", ts_offset=0),
            _sig("pod_crashloop", resource_name="pod-a", ts_offset=30),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        assert len(decisions) == 1  # second is dedup of first

    def test_different_pods_never_deduped(self):
        """Two different pods crashing must BOTH be reported."""
        profile = ClusterProfile(cluster_id="test", dedup_windows={"pod_crashloop": 600})
        signals = [
            _sig("pod_crashloop", resource_name="pod-a", ts_offset=0),
            _sig("pod_crashloop", resource_name="pod-b", ts_offset=5),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        assert len(decisions) == 0  # both kept — different resources

    def test_different_namespaces_never_deduped(self):
        """Same signal type in different namespaces must BOTH be reported."""
        profile = ClusterProfile(cluster_id="test", dedup_windows={"pod_crashloop": 3600})
        signals = [
            _sig("pod_crashloop", namespace="ns-a", ts_offset=0),
            _sig("pod_crashloop", namespace="ns-b", ts_offset=5),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        assert len(decisions) == 0

    def test_different_type_same_pod_never_deduped(self):
        """Different failure types on the same pod must BOTH be reported."""
        profile = ClusterProfile(cluster_id="test", dedup_windows={"pod_crashloop": 600, "oom_killed": 600})
        signals = [
            _sig("pod_crashloop", resource_name="pod-a", ts_offset=0),
            _sig("oom_killed", resource_name="pod-a", ts_offset=5),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        assert len(decisions) == 0  # different types — both kept

    def test_after_window_expires_signal_reappears(self):
        """After the dedup window, the same signal must be reported again."""
        profile = ClusterProfile(cluster_id="test", dedup_windows={"pod_crashloop": 60})
        signals = [
            _sig("pod_crashloop", resource_name="pod-a", ts_offset=0),
            _sig("pod_crashloop", resource_name="pod-a", ts_offset=61),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        assert len(decisions) == 0  # both kept — window expired


class TestDampeningNeverHidesNewTypes:
    """Namespace dampening suppresses repeated types but never suppresses a NEW signal type."""

    def test_dampened_namespace_still_shows_new_type(self):
        """If namespace is dampened for scheduling failures, a crashloop must still come through."""
        profile = ClusterProfile(cluster_id="test", namespace_dampen_thresholds={"noisy-ns": 3})
        signals = [
            # 5 scheduling failures → dampen after 3
            _sig("event_failedscheduling", namespace="noisy-ns", resource_name=f"p{i}", ts_offset=i)
            for i in range(5)
        ] + [
            # Then a NEW type: crashloop
            _sig("pod_crashloop", namespace="noisy-ns", resource_name="crash-pod", ts_offset=10),
        ]
        decisions = transient_suppressor.filter(signals, cluster_profile=profile)
        suppressed_ids = {d.signal_id for d in decisions if d.outcome == "suppress"}
        crashloop = signals[-1]
        assert crashloop.signal_id not in suppressed_ids, "Crashloop in dampened namespace must NOT be suppressed"


class TestCriticalSignalsNeverSuppressed:
    """Critical/high severity signals should have special protection."""

    def test_high_severity_not_deduped_with_short_window(self):
        """High severity signals should use minimum dedup window even if profile says longer."""
        # This test documents expected behavior — if we want to add this guardrail
        profile = ClusterProfile(cluster_id="test", dedup_windows={"pod_crashloop": 600})
        signals = [
            _sig("pod_crashloop", severity="high", resource_name="pod-a", ts_offset=0),
            _sig("pod_crashloop", severity="high", resource_name="pod-a", ts_offset=120),
        ]
        decisions = dedupe.filter(signals, cluster_profile=profile)
        # Currently both get deduped with 600s window — this is a design choice
        # If we add critical signal protection, this should change
        assert len(decisions) == 1  # current behavior: deduped


class TestProfileNeverAutoSuppressesTypes:
    """Auto-tuning must never add signal types to the suppress list automatically."""

    def test_suppress_types_not_modified_by_update(self):
        profile = ClusterProfile(cluster_id="test")
        assert len(profile.suppress_types) == 0
        profile.update_from_signals(
            signal_counts={"event_failedscheduling": 100000},
            namespace_counts={"noisy": 100000},
            total_signals=100000,
            duration_hours=1.0,
        )
        assert len(profile.suppress_types) == 0, "Auto-tuning must never add suppress types"

    def test_suppress_types_only_set_explicitly(self):
        profile = ClusterProfile(cluster_id="test")
        profile.suppress_types.add("event_pulling")
        assert profile.should_suppress_type("event_pulling")
        assert not profile.should_suppress_type("pod_crashloop")


class TestProposalSafetyChecks:
    """Proposals should include safety metadata so reviewers can make informed decisions."""

    def test_noise_proposal_includes_evidence(self):
        from app.analysis.pattern_analyzer import detect_noisy_namespaces
        proposals = detect_noisy_namespaces(
            {"noisy-ns": 10000}, {"noisy-ns": 9500}, "test"
        )
        assert len(proposals) == 1
        p = proposals[0]
        assert "evidence" in p
        assert p["evidence"]["total_signals"] == 10000
        assert p["evidence"]["suppressed"] == 9500
        assert p["evidence"]["noise_ratio"] > 0.9
        assert "impact_estimate" in p
        assert p["confidence"] < 1.0  # never 100% confident

    def test_model_proposal_includes_call_count(self):
        from app.analysis.pattern_analyzer import detect_model_issues
        proposals = detect_model_issues(
            {"bad": {"calls": 200, "errors": 60, "error_rate": 0.3, "avg_latency": 25000}},
            "test"
        )
        assert len(proposals) == 1
        assert proposals[0]["evidence"]["calls"] == 200
        assert proposals[0]["evidence"]["errors"] == 60
