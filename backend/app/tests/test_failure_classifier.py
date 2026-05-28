"""Tests for failure_classifier nano-agent — deterministic pattern matching
against known K8s failure classes before handing off to the LLM."""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import pytest

from app.domain.models import NormalizedSignal
from app.nanoagents import failure_classifier


def _make_signal(
    signal_type: str = "event_unknown",
    resource_kind: str = "Pod",
    severity: str = "high",
    namespace: str = "ns-prod-001",
    resource_name: str = "test-resource",
    evidence: Optional[dict] = None,
    labels: Optional[dict] = None,
) -> NormalizedSignal:
    return NormalizedSignal(
        signal_id=uuid4(),
        cluster_id=uuid4(),
        namespace=namespace,
        resource_kind=resource_kind,
        resource_name=resource_name,
        signal_type=signal_type,
        severity=severity,
        confidence=0.95,
        evidence=evidence or {},
        labels=labels or {},
        timestamp=datetime.now(timezone.utc),
    )


# ── Pattern-matching tests ──────────────────────────────────────────


class TestImagePullBackoff:
    def test_matches_errimagepull(self):
        sig = _make_signal(evidence={"message": "Failed to pull image: ErrImagePull"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        d = decisions[0]
        assert d.outcome == "enrich"
        assert d.evidence["failure_class"] == "image_pull_backoff"
        assert d.evidence["confidence"] == 1.0
        assert d.evidence["source"] == "deterministic_pattern"

    def test_matches_imagepullbackoff(self):
        sig = _make_signal(evidence={"message": "Back-off pulling image"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "image_pull_backoff"

    def test_matches_failed_to_pull(self):
        sig = _make_signal(evidence={"message": "Failed to pull image registry.io/app:v2"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "image_pull_backoff"


class TestCrashLoop:
    def test_matches_crashloopbackoff(self):
        sig = _make_signal(evidence={"message": "CrashLoopBackOff"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "pods_crashlooping"

    def test_matches_backoff_restarting(self):
        sig = _make_signal(evidence={"message": "Back-off restarting failed container"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "pods_crashlooping"


class TestOOMKilled:
    def test_matches_oomkill(self):
        sig = _make_signal(evidence={"message": "container was OOMKill"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "oom_killed"

    def test_matches_exit_code_137(self):
        sig = _make_signal(evidence={"message": "container exited with exit code 137"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "oom_killed"


class TestNodePressure:
    def test_matches_nodenotready(self):
        sig = _make_signal(
            resource_kind="Node", severity="critical",
            evidence={"message": "NodeNotReady condition detected"},
        )
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "node_pressure"

    def test_matches_diskpressure(self):
        sig = _make_signal(
            resource_kind="Node",
            evidence={"message": "DiskPressure condition is True"},
        )
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "node_pressure"


class TestSchedulingFailed:
    def test_matches_failedscheduling(self):
        sig = _make_signal(evidence={
            "message": "FailedScheduling: 0/3 nodes are available: insufficient cpu"
        })
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "scheduling_failed"


class TestQuotaExceeded:
    def test_matches_exceeded_quota(self):
        sig = _make_signal(evidence={
            "message": "exceeded quota: cpu-limit, requested: 4, used: 8, limited: 10"
        })
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "quota_exceeded"


class TestCertificateError:
    def test_matches_x509(self):
        sig = _make_signal(evidence={
            "message": "x509: certificate has expired or is not yet valid"
        })
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "certificate_error"


class TestPVCBindingFailed:
    def test_matches_no_pv_available(self):
        sig = _make_signal(
            resource_kind="PersistentVolumeClaim",
            evidence={"message": "no persistent volumes available for this claim"},
        )
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "pvc_binding_failed"


class TestVolumeMountFailed:
    def test_matches_failedmount(self):
        sig = _make_signal(evidence={
            "message": "FailedMount: Unable to attach or mount volumes"
        })
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "volume_mount_failed"


class TestDNSResolutionFailed:
    def test_matches_dns_resolution(self):
        sig = _make_signal(evidence={
            "message": "dns resolution failed for svc.cluster.local"
        })
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].evidence["failure_class"] == "dns_resolution_failed"


# ── Pass-through (no match) ─────────────────────────────────────────


class TestPassThrough:
    def test_no_message_in_evidence_passes(self):
        sig = _make_signal(evidence={"reason": "Started"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].outcome == "keep"
        assert decisions[0].reason_code == "no_pattern_match"
        assert decisions[0].evidence.get("action") == "pass"

    def test_benign_message_passes(self):
        sig = _make_signal(evidence={"message": "Successfully pulled image"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        assert decisions[0].outcome == "keep"

    def test_empty_signals_returns_empty(self):
        decisions = failure_classifier.filter([])
        assert decisions == []


# ── Batch behavior ──────────────────────────────────────────────────


class TestBatchBehavior:
    def test_mixed_batch_classifies_and_passes(self):
        """A batch with one matching and one non-matching signal."""
        sig_match = _make_signal(evidence={"message": "CrashLoopBackOff"})
        sig_benign = _make_signal(evidence={"message": "Running normally"})
        decisions = failure_classifier.filter([sig_match, sig_benign])

        assert len(decisions) == 2
        classified = [d for d in decisions if d.outcome == "enrich"]
        passed = [d for d in decisions if d.outcome == "keep"]
        assert len(classified) == 1
        assert len(passed) == 1
        assert classified[0].evidence["failure_class"] == "pods_crashlooping"


# ── Decision metadata ──────────────────────────────────────────────


class TestDecisionMetadata:
    def test_decision_includes_remediation(self):
        sig = _make_signal(evidence={"message": "CrashLoopBackOff"})
        decisions = failure_classifier.filter([sig])
        assert len(decisions) == 1
        d = decisions[0]
        assert "remediation" in d.evidence
        assert isinstance(d.evidence["remediation"], list)
        assert len(d.evidence["remediation"]) > 0

    def test_decision_includes_severity_from_yaml(self):
        sig = _make_signal(evidence={"message": "CrashLoopBackOff"})
        decisions = failure_classifier.filter([sig])
        assert decisions[0].evidence["class_severity"] == "high"

    def test_filter_name_is_correct(self):
        sig = _make_signal(evidence={"message": "CrashLoopBackOff"})
        decisions = failure_classifier.filter([sig])
        assert decisions[0].filter_name == "FailureClassifierAgent"


# ── Pattern loading ─────────────────────────────────────────────────


class TestPatternLoading:
    def test_classes_loaded_from_yaml(self):
        """Sanity: at least 10 failure classes loaded from the YAML."""
        classes = failure_classifier.get_failure_classes()
        assert len(classes) >= 10

    def test_each_class_has_pattern(self):
        for name, cls in failure_classifier.get_failure_classes().items():
            assert "pattern" in cls, f"class {name} missing pattern"
            assert "severity" in cls, f"class {name} missing severity"
