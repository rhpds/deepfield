"""Tests for signal routing."""

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models import CandidateFinding, FilterDecision, NormalizedSignal
from app.routing.signal_router import route_signals, create_reasoning_tasks


def _signal(signal_type="pod_running", severity="info"):
    return NormalizedSignal(
        signal_id=uuid4(),
        cluster_id=uuid4(),
        namespace="ns-prod-001",
        resource_kind="Pod",
        resource_name="pod-abc",
        signal_type=signal_type,
        severity=severity,
        confidence=0.95,
        timestamp=datetime.now(timezone.utc),
    )


def test_signal_router_drops_info_noise():
    signals = [
        _signal("pod_running", "info"),
        _signal("route_ready", "info"),
        _signal("pod_crashloop", "high"),
    ]
    result = route_signals(signals, decisions=[])
    assert result["dropped_count"] == 2
    assert result["kept_count"] == 1
    assert result["kept"][0].signal_type == "pod_crashloop"


def test_signal_router_escalates_high_severity():
    sig = _signal("pod_crashloop", "high")
    escalation = FilterDecision(
        signal_id=sig.signal_id, filter_name="PodHealthAgent",
        outcome="escalate", reason_code="crashloop",
    )
    result = route_signals([sig], decisions=[escalation])
    assert result["kept_count"] == 1


def test_reasoning_task_created_for_high_value_finding():
    finding = CandidateFinding(
        clusters=[uuid4()],
        namespaces=["ns-prod-001"],
        signal_ids=[uuid4(), uuid4()],
        finding_type="namespace_correlation",
        severity="high",
        summary="Multiple failures in ns-prod-001",
    )
    tasks = create_reasoning_tasks([finding])
    assert len(tasks) == 1
    assert tasks[0].task_type == "root_cause_analysis"  # high severity → macro tier → RCA
    assert tasks[0].model_preference in ("deepseek", "phi4", "qwen3", "qwen3b")


def test_reasoning_task_not_created_for_dropped_signal():
    finding = CandidateFinding(
        clusters=[uuid4()],
        namespaces=["ns-dev-001"],
        signal_ids=[uuid4()],
        finding_type="namespace_correlation",
        severity="info",
        summary="Info-level signals in dev namespace",
    )
    tasks = create_reasoning_tasks([finding])
    assert len(tasks) == 0
