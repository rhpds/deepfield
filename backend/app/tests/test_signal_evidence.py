"""TDD tests for signal evidence enrichment across all signal types.

Tests the full evidence chain: collector → normalizer → correlation → prompt.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4, uuid5, NAMESPACE_DNS

from app.domain.models import RawSignal, NormalizedSignal
from app.normalizers.signal_normalizer import normalize_signal, _extract_evidence
from app.correlation.engine import correlate
from app.routing.signal_router import create_reasoning_tasks, _build_evidence_block


def _raw(signal_type: str, payload: dict, namespace: str = "test-ns") -> RawSignal:
    return RawSignal(
        signal_id=uuid4(),
        cluster_id=uuid5(NAMESPACE_DNS, "test-cluster"),
        namespace=namespace,
        resource_kind="Pod",
        resource_name="test-pod-abc123",
        source="live:infra01",
        signal_type=signal_type,
        raw_payload=payload,
        timestamp=datetime.now(timezone.utc),
    )


# === Evidence extraction tests ===

class TestEvidenceExtraction:
    def test_crashloop_evidence_includes_restart_count(self):
        raw = _raw("pod_crashloop", {"restartCount": 15, "reason": "CrashLoopBackOff", "container": "app"})
        ev = _extract_evidence(raw)
        assert ev["restartCount"] == 15
        assert ev["reason"] == "CrashLoopBackOff"
        assert ev["container"] == "app"

    def test_crashloop_evidence_includes_exit_details(self):
        raw = _raw("pod_crashloop", {
            "restartCount": 8, "reason": "CrashLoopBackOff",
            "container": "worker", "image": "myapp:v2.1",
            "exit_code": 137, "exit_reason": "OOMKilled",
            "exit_message": "container exceeded memory limit",
        })
        ev = _extract_evidence(raw)
        assert ev["exit_code"] == 137
        assert ev["exit_reason"] == "OOMKilled"
        assert ev["exit_message"] == "container exceeded memory limit"
        assert ev["image"] == "myapp:v2.1"

    def test_crashloop_evidence_includes_owner_and_node(self):
        raw = _raw("pod_crashloop", {
            "restartCount": 5, "reason": "CrashLoopBackOff",
            "app": "payment-service", "owner": "Deployment/payment-service",
            "node": "worker-3.cluster.local",
        })
        ev = _extract_evidence(raw)
        assert ev["app"] == "payment-service"
        assert ev["owner"] == "Deployment/payment-service"
        assert ev["node"] == "worker-3.cluster.local"

    def test_imagepullbackoff_evidence_includes_image(self):
        raw = _raw("pod_imagepullbackoff", {
            "reason": "ImagePullBackOff", "image": "registry.io/myapp:bad-tag",
            "app": "frontend", "owner": "Deployment/frontend",
        })
        ev = _extract_evidence(raw)
        assert ev["image"] == "registry.io/myapp:bad-tag"
        assert ev["reason"] == "ImagePullBackOff"
        assert ev["app"] == "frontend"

    def test_pending_pod_evidence_includes_schedule_reason(self):
        raw = _raw("pod_pending", {
            "phase": "Pending",
            "schedule_reason": "Unschedulable",
            "schedule_message": "0/3 nodes available: insufficient memory",
            "owner": "Deployment/big-app",
        })
        ev = _extract_evidence(raw)
        assert ev["schedule_reason"] == "Unschedulable"
        assert ev["schedule_message"] == "0/3 nodes available: insufficient memory"
        assert ev["phase"] == "Pending"

    def test_event_evidence_includes_message_and_count(self):
        raw = _raw("event_backoff", {
            "reason": "BackOff", "message": "Back-off restarting failed container",
            "count": 42,
        })
        ev = _extract_evidence(raw)
        assert ev["message"] == "Back-off restarting failed container"
        assert ev["count"] == 42
        assert ev["reason"] == "BackOff"

    def test_event_backofflimitexceeded_evidence(self):
        raw = _raw("event_backofflimitexceeded", {
            "reason": "BackoffLimitExceeded",
            "message": "Job has reached the specified backoff limit",
            "count": 1,
        })
        ev = _extract_evidence(raw)
        assert ev["message"] == "Job has reached the specified backoff limit"

    def test_node_pressure_evidence(self):
        raw = _raw("node_pressure", {"condition": "MemoryPressure"}, namespace="")
        raw.resource_kind = "Node"
        raw.resource_name = "worker-1"
        ev = _extract_evidence(raw)
        assert ev["condition"] == "MemoryPressure"

    def test_empty_payload_produces_minimal_evidence(self):
        raw = _raw("pod_running", {})
        ev = _extract_evidence(raw)
        assert ev["source"] == "live:infra01"
        assert ev["signal_type"] == "pod_running"
        assert "restartCount" not in ev


# === Severity classification tests ===

class TestSeverityClassification:
    def test_pod_running_is_info(self):
        norm = normalize_signal(_raw("pod_running", {}))
        assert norm.severity == "info"

    def test_pod_crashloop_is_high(self):
        norm = normalize_signal(_raw("pod_crashloop", {"restartCount": 10}))
        assert norm.severity == "high"

    def test_pod_imagepullbackoff_is_high(self):
        norm = normalize_signal(_raw("pod_imagepullbackoff", {"reason": "ImagePullBackOff"}))
        assert norm.severity == "high"

    def test_pod_pending_is_low(self):
        norm = normalize_signal(_raw("pod_pending", {"phase": "Pending"}))
        assert norm.severity == "low"

    def test_node_pressure_is_critical(self):
        norm = normalize_signal(_raw("node_pressure", {"condition": "MemoryPressure"}))
        assert norm.severity == "critical"

    def test_event_backoff_is_high(self):
        norm = normalize_signal(_raw("event_backoff", {"reason": "BackOff"}))
        assert norm.severity == "high"

    def test_event_backofflimitexceeded_is_high(self):
        norm = normalize_signal(_raw("event_backofflimitexceeded", {}))
        assert norm.severity == "high"

    def test_event_crashloopbackoff_is_high(self):
        norm = normalize_signal(_raw("event_crashloopbackoff", {}))
        assert norm.severity == "high"

    def test_event_imagepullbackoff_is_high(self):
        norm = normalize_signal(_raw("event_imagepullbackoff", {}))
        assert norm.severity == "high"

    def test_event_unhealthy_is_high(self):
        norm = normalize_signal(_raw("event_unhealthy", {}))
        assert norm.severity == "high"

    def test_event_nodenotready_is_critical(self):
        norm = normalize_signal(_raw("event_nodenotready", {}))
        assert norm.severity == "critical"

    def test_event_invalidconfiguration_is_high(self):
        norm = normalize_signal(_raw("event_invalidconfiguration", {}))
        assert norm.severity == "high"

    def test_event_failedscheduling_is_medium(self):
        norm = normalize_signal(_raw("event_failedscheduling", {}))
        assert norm.severity == "medium"

    def test_event_pulling_is_info(self):
        norm = normalize_signal(_raw("event_pulling", {}))
        assert norm.severity == "info"

    def test_event_started_is_info(self):
        norm = normalize_signal(_raw("event_started", {}))
        assert norm.severity == "info"

    def test_event_killing_is_low(self):
        norm = normalize_signal(_raw("event_killing", {}))
        assert norm.severity == "low"

    def test_unknown_event_defaults_to_medium(self):
        norm = normalize_signal(_raw("event_somethingweird", {}))
        assert norm.severity == "medium"


# === Correlation evidence preservation tests ===

class TestCorrelationEvidence:
    def _make_signals(self, types_and_payloads, namespace="test-ns"):
        signals = []
        for sig_type, payload in types_and_payloads:
            raw = _raw(sig_type, payload, namespace)
            signals.append(normalize_signal(raw))
        return signals

    def test_correlation_preserves_per_signal_details(self):
        signals = self._make_signals([
            ("pod_crashloop", {"restartCount": 15, "reason": "CrashLoopBackOff", "container": "app", "owner": "Deployment/myapp"}),
            ("event_backoff", {"reason": "BackOff", "message": "Back-off restarting failed container", "count": 12}),
        ])
        findings = correlate(signals)
        assert len(findings) > 0
        f = findings[0]
        assert "signals" in f.evidence
        signal_details = f.evidence["signals"]
        assert len(signal_details) == 2
        for s in signal_details:
            assert "signal_type" in s
            assert "resource_name" in s
            assert "evidence" in s

    def test_correlation_evidence_has_restart_count(self):
        signals = self._make_signals([
            ("pod_crashloop", {"restartCount": 20, "reason": "CrashLoopBackOff"}),
            ("event_backoff", {"reason": "BackOff", "message": "restarting"}),
        ])
        findings = correlate(signals)
        f = findings[0]
        crashloop_sig = next(s for s in f.evidence["signals"] if s["signal_type"] == "pod_crashloop")
        assert crashloop_sig["evidence"]["restartCount"] == 20

    def test_correlation_evidence_has_event_message(self):
        signals = self._make_signals([
            ("event_backoff", {"reason": "BackOff", "message": "Back-off restarting failed container", "count": 5}),
            ("event_backofflimitexceeded", {"reason": "BackoffLimitExceeded", "message": "Job reached backoff limit"}),
        ])
        findings = correlate(signals)
        f = findings[0]
        backoff_sig = next(s for s in f.evidence["signals"] if s["signal_type"] == "event_backoff")
        assert "Back-off restarting" in backoff_sig["evidence"]["message"]


# === Prompt construction tests ===

class TestPromptConstruction:
    def _make_finding(self, severity="high"):
        signals = []
        for sig_type, payload in [
            ("pod_crashloop", {"restartCount": 15, "reason": "CrashLoopBackOff", "container": "app", "exit_code": 1, "owner": "Deployment/myapp"}),
            ("event_backoff", {"reason": "BackOff", "message": "Back-off restarting", "count": 10}),
        ]:
            raw = _raw(sig_type, payload, "production")
            signals.append(normalize_signal(raw))

        findings = correlate(signals)
        if findings:
            return findings[0]
        return None

    def test_rca_prompt_includes_system_prompt(self):
        f = self._make_finding()
        assert f is not None
        tasks = create_reasoning_tasks([f])
        assert len(tasks) > 0
        prompt = tasks[0].prompt
        assert "Root Cause Analysis Agent" in prompt
        assert "remediation" in prompt

    def test_rca_prompt_includes_structured_evidence(self):
        f = self._make_finding()
        tasks = create_reasoning_tasks([f])
        prompt = tasks[0].prompt
        assert "Evidence:" in prompt
        evidence_json = prompt.split("Evidence:\n", 1)[1]
        data = json.loads(evidence_json)
        assert "signals" in data
        assert data["signal_count"] == 2
        assert data["severity"] == "high"

    def test_rca_prompt_evidence_has_resource_names(self):
        f = self._make_finding()
        tasks = create_reasoning_tasks([f])
        prompt = tasks[0].prompt
        evidence_json = prompt.split("Evidence:\n", 1)[1]
        data = json.loads(evidence_json)
        for sig in data["signals"]:
            assert "resource_name" in sig
            assert sig["resource_name"] != ""

    def test_rca_prompt_evidence_has_exit_details(self):
        f = self._make_finding()
        tasks = create_reasoning_tasks([f])
        prompt = tasks[0].prompt
        evidence_json = prompt.split("Evidence:\n", 1)[1]
        data = json.loads(evidence_json)
        crashloop = next(s for s in data["signals"] if s["signal_type"] == "pod_crashloop")
        assert crashloop["evidence"]["exit_code"] == 1
        assert crashloop["evidence"]["owner"] == "Deployment/myapp"

    def test_medium_severity_gets_triage_prompt(self):
        signals = []
        for sig_type, payload in [
            ("event_failedscheduling", {"reason": "FailedScheduling", "message": "no nodes available"}),
            ("pod_pending", {"phase": "Pending", "schedule_reason": "Unschedulable"}),
        ]:
            raw = _raw(sig_type, payload, "staging")
            signals.append(normalize_signal(raw))
        findings = correlate(signals)
        if findings:
            tasks = create_reasoning_tasks(findings)
            if tasks:
                assert "Triage Agent" in tasks[0].prompt

    def test_evidence_block_structure(self):
        from app.domain.models import CandidateFinding
        f = CandidateFinding(
            finding_id=uuid4(), clusters=[uuid4()], namespaces=["prod"],
            signal_ids=[uuid4(), uuid4()], finding_type="namespace_correlation",
            severity="high", correlation_keys={}, summary="test",
            evidence={"signal_types": ["pod_crashloop"], "signals": [
                {"signal_type": "pod_crashloop", "resource_name": "app-123", "evidence": {"restartCount": 5}}
            ]},
        )
        block = _build_evidence_block(f)
        assert block["finding_type"] == "namespace_correlation"
        assert block["severity"] == "high"
        assert block["signal_count"] == 2
        assert len(block["signals"]) == 1
        assert block["signals"][0]["resource_name"] == "app-123"
