"""E2E Integration tests — DeepField ↔ Launchpad ↔ StarGate.

Validates signal injection, nano-agent processing, and event publishing.
"""

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models import NormalizedSignal, FilterDecision
from app.nanoagents.launchpad_session import filter as launchpad_filter
from app.nanoagents.stargate_evaluation import filter as stargate_filter
from app.nanoagents.pipeline import run_pipeline


class TestLaunchpadSignalProcessing:
    def test_launchpad_lab_failed_escalates(self):
        signals = [NormalizedSignal(
            signal_id=uuid4(), cluster_id=uuid4(),
            namespace="demo-ns", resource_kind="LaunchpadSession",
            resource_name="sess-001", signal_type="launchpad_lab_failed",
            severity="high", confidence=0.95,
            evidence={"labId": "inference-overdrive", "resource_name": "sess-001"},
            timestamp=datetime.now(timezone.utc),
        )]
        decisions = launchpad_filter(signals)
        assert len(decisions) == 1
        assert decisions[0].outcome == "escalate"
        assert decisions[0].reason_code == "lab_failed"

    def test_launchpad_lab_expired_keeps(self):
        signals = [NormalizedSignal(
            signal_id=uuid4(), cluster_id=uuid4(),
            namespace="demo-ns", resource_kind="LaunchpadSession",
            resource_name="sess-002", signal_type="launchpad_lab_expired",
            severity="low", confidence=0.85,
            timestamp=datetime.now(timezone.utc),
        )]
        decisions = launchpad_filter(signals)
        assert len(decisions) == 1
        assert decisions[0].outcome == "keep"


class TestStarGateSignalProcessing:
    def test_stargate_stage_failed_escalates(self):
        signals = [NormalizedSignal(
            signal_id=uuid4(), cluster_id=uuid4(),
            namespace="stargate-ns", resource_kind="StarGateRun",
            resource_name="run-001", signal_type="stargate_stage_failed",
            severity="high", confidence=0.95,
            evidence={"failure_class": "pods_crashlooping"},
            timestamp=datetime.now(timezone.utc),
        )]
        decisions = stargate_filter(signals)
        assert len(decisions) == 1
        assert decisions[0].outcome == "escalate"

    def test_stargate_stage_passed_drops(self):
        signals = [NormalizedSignal(
            signal_id=uuid4(), cluster_id=uuid4(),
            namespace="stargate-ns", resource_kind="StarGateRun",
            resource_name="run-002", signal_type="stargate_stage_passed",
            severity="info", confidence=0.99,
            timestamp=datetime.now(timezone.utc),
        )]
        decisions = stargate_filter(signals)
        assert len(decisions) == 1
        assert decisions[0].outcome == "drop"


class TestFullPipeline:
    def test_pipeline_processes_mixed_signals(self):
        signals = [
            NormalizedSignal(
                signal_id=uuid4(), cluster_id=uuid4(),
                namespace="ns-1", resource_kind="Pod",
                resource_name="pod-1", signal_type="pod_running",
                severity="info", confidence=0.99,
                timestamp=datetime.now(timezone.utc),
            ),
            NormalizedSignal(
                signal_id=uuid4(), cluster_id=uuid4(),
                namespace="ns-1", resource_kind="Pod",
                resource_name="pod-2", signal_type="pod_crashloop",
                severity="high", confidence=0.95,
                evidence={"restartCount": 5},
                timestamp=datetime.now(timezone.utc),
            ),
        ]
        result = run_pipeline(signals)
        assert result["total_signals"] == 2
        assert len(result["escalated"]) >= 1
        assert result["retained_count"] >= 1
