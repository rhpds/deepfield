"""Tests for correlation engine."""

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models import NormalizedSignal
from app.correlation.engine import correlate_by_namespace, correlate_cross_cluster


def _signal(signal_type="pod_crashloop", severity="high", namespace="ns-prod-001",
            cluster_id=None):
    return NormalizedSignal(
        signal_id=uuid4(),
        cluster_id=cluster_id or uuid4(),
        namespace=namespace,
        resource_kind="Pod",
        resource_name=f"pod-{uuid4().hex[:6]}",
        signal_type=signal_type,
        severity=severity,
        confidence=0.95,
        timestamp=datetime.now(timezone.utc),
    )


def test_correlation_engine_groups_same_namespace_signals():
    cid = uuid4()
    signals = [
        _signal("pod_crashloop", "high", "ns-prod-001", cid),
        _signal("pod_imagepullbackoff", "high", "ns-prod-001", cid),
        _signal("route_unhealthy", "high", "ns-prod-001", cid),
    ]
    findings = correlate_by_namespace(signals)
    assert len(findings) >= 1
    f = findings[0]
    assert f.finding_type == "namespace_correlation"
    assert len(f.signal_ids) >= 2
    assert "ns-prod-001" in f.namespaces


def test_correlation_engine_groups_cross_cluster_model_latency():
    cid1, cid2 = uuid4(), uuid4()
    signals = [
        _signal("kserve_not_ready", "high", "ns-ml-001", cid1),
        _signal("kserve_not_ready", "high", "ns-ml-002", cid2),
    ]
    findings = correlate_cross_cluster(signals)
    assert len(findings) >= 1
    f = findings[0]
    assert f.finding_type == "cross_cluster_correlation"
    assert len(f.clusters) == 2
