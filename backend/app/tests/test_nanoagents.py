"""Tests for nano-agent filters."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.domain.models import NormalizedSignal
from app.nanoagents import (
    pod_health, route_health, pvc_health, node_pressure,
    namespace_quota, kserve_endpoint, dedupe, transient_suppressor,
)


def _make_signal(signal_type: str, resource_kind: str = "Pod", severity: str = "high",
                 namespace: str = "ns-prod-001", resource_name: str = "test-resource",
                 evidence: dict = None, timestamp: datetime = None, cluster_id=None):
    return NormalizedSignal(
        signal_id=uuid4(),
        cluster_id=cluster_id or uuid4(),
        namespace=namespace,
        resource_kind=resource_kind,
        resource_name=resource_name,
        signal_type=signal_type,
        severity=severity,
        confidence=0.95,
        evidence=evidence or {},
        timestamp=timestamp or datetime.now(timezone.utc),
    )


def test_pod_health_agent_detects_crashloop():
    signals = [
        _make_signal("pod_crashloop", "Pod"),
        _make_signal("pod_running", "Pod", severity="info"),
        _make_signal("pod_imagepullbackoff", "Pod"),
    ]
    decisions = pod_health.filter(signals)
    assert len(decisions) == 2
    assert all(d.outcome == "escalate" for d in decisions)
    reason_codes = {d.reason_code for d in decisions}
    assert "pod_crashloop_detected" in reason_codes
    assert "pod_imagepullbackoff_detected" in reason_codes


def test_route_health_agent_detects_no_endpoints():
    signals = [
        _make_signal("route_unhealthy", "Route"),
        _make_signal("route_ready", "Route", severity="info"),
    ]
    decisions = route_health.filter(signals)
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"
    assert decisions[0].reason_code == "route_unhealthy"


def test_pvc_health_agent_detects_pending():
    signals = [
        _make_signal("pvc_pending", "PersistentVolumeClaim", severity="medium"),
        _make_signal("pvc_bound", "PersistentVolumeClaim", severity="info"),
    ]
    decisions = pvc_health.filter(signals)
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"


def test_node_pressure_agent_detects_pressure():
    signals = [
        _make_signal("node_pressure", "Node", severity="critical",
                     evidence={"condition": "MemoryPressure"}),
        _make_signal("node_ready", "Node", severity="info"),
    ]
    decisions = node_pressure.filter(signals)
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"
    assert "memorypressure" in decisions[0].reason_code


def test_namespace_quota_agent_detects_exceeded():
    signals = [
        _make_signal("namespace_quota_exceeded", "ResourceQuota", severity="medium",
                     evidence={"resource": "cpu"}),
    ]
    decisions = namespace_quota.filter(signals)
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"


def test_kserve_agent_detects_not_ready():
    signals = [
        _make_signal("kserve_not_ready", "InferenceService"),
        _make_signal("kserve_ready", "InferenceService", severity="info"),
    ]
    decisions = kserve_endpoint.filter(signals)
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"


def test_dedupe_agent_removes_duplicate_signals():
    cid = uuid4()
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    signals = [
        _make_signal("pod_crashloop", "Pod", namespace="ns-a", resource_name="pod-1",
                     cluster_id=cid, timestamp=base_time),
        _make_signal("pod_crashloop", "Pod", namespace="ns-a", resource_name="pod-1",
                     cluster_id=cid, timestamp=base_time + timedelta(seconds=10)),
        _make_signal("pod_crashloop", "Pod", namespace="ns-a", resource_name="pod-1",
                     cluster_id=cid, timestamp=base_time + timedelta(seconds=20)),
    ]
    decisions = dedupe.filter(signals)
    assert len(decisions) == 2
    assert all(d.outcome == "dedupe" for d in decisions)


def test_transient_suppressor_suppresses_short_startup_noise():
    cid = uuid4()
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    signals = [
        _make_signal("pod_pending", "Pod", severity="low", namespace="ns-a",
                     resource_name="pod-1", cluster_id=cid, timestamp=base_time),
        _make_signal("pod_pending", "Pod", severity="low", namespace="ns-a",
                     resource_name="pod-1", cluster_id=cid,
                     timestamp=base_time + timedelta(seconds=30)),
        _make_signal("pod_pending", "Pod", severity="low", namespace="ns-a",
                     resource_name="pod-1", cluster_id=cid,
                     timestamp=base_time + timedelta(seconds=60)),
    ]
    decisions = transient_suppressor.filter(signals, window_seconds=120)
    assert len(decisions) == 2
    assert all(d.outcome == "suppress" for d in decisions)
