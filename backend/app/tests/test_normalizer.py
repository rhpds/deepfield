"""Tests for signal normalizer."""

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models import RawSignal
from app.normalizers.signal_normalizer import normalize_signal, normalize_batch


def test_normalizer_converts_pod_crashloop_to_normalized_signal():
    raw = RawSignal(
        cluster_id=uuid4(),
        namespace="ns-prod-001",
        resource_kind="Pod",
        resource_name="api-gateway-abc12",
        source="synthetic",
        signal_type="pod_crashloop",
        raw_payload={"restartCount": 12, "reason": "CrashLoopBackOff"},
        timestamp=datetime.now(timezone.utc),
    )
    norm = normalize_signal(raw)
    assert norm.signal_id == raw.signal_id
    assert norm.severity == "high"
    assert norm.confidence == 0.95
    assert norm.deterministic is True
    assert "restartCount" in norm.evidence
    assert norm.resource_kind == "Pod"


def test_normalizer_classifies_info_signals():
    raw = RawSignal(
        cluster_id=uuid4(),
        namespace="ns-prod-001",
        resource_kind="Pod",
        resource_name="web-server-xyz",
        source="synthetic",
        signal_type="pod_running",
        timestamp=datetime.now(timezone.utc),
    )
    norm = normalize_signal(raw)
    assert norm.severity == "info"
    assert norm.confidence == 0.99


def test_normalizer_batch():
    raws = [
        RawSignal(
            cluster_id=uuid4(), namespace="ns-1", resource_kind="Pod",
            resource_name=f"pod-{i}", source="synthetic",
            signal_type="pod_running", timestamp=datetime.now(timezone.utc),
        )
        for i in range(5)
    ]
    norms = normalize_batch(raws)
    assert len(norms) == 5
    assert all(n.severity == "info" for n in norms)
