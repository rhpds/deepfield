"""Tests for domain-separated nano-agents."""

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models import NormalizedSignal


def _sig(signal_type="pod_crashloop", namespace="test-ns", resource_name="test-pod",
         resource_kind="Pod", severity="high", evidence=None):
    return NormalizedSignal(
        signal_id=uuid4(), cluster_id=uuid4(), namespace=namespace,
        resource_kind=resource_kind, resource_name=resource_name,
        signal_type=signal_type, severity=severity, confidence=0.95,
        evidence=evidence or {}, timestamp=datetime.now(timezone.utc),
    )


# === InfraNoiseAgent ===

def test_infra_noise_suppresses_coredns():
    from app.nanoagents.infra_noise import filter
    decisions = filter([_sig("event_backoff", resource_name="coredns-abc", namespace="openshift-dns")])
    assert len(decisions) == 1
    assert decisions[0].outcome == "suppress"
    assert decisions[0].reason_code == "known_noisy_component"


def test_infra_noise_passes_non_noisy():
    from app.nanoagents.infra_noise import filter
    decisions = filter([_sig("pod_crashloop", resource_name="my-app-123", namespace="production")])
    assert len(decisions) == 0


# === AppLogAgent ===

def test_app_log_escalates_critical():
    from app.nanoagents.app_log import filter
    decisions = filter([_sig("splunk_critical_alert", resource_kind="SplunkAlert",
                             evidence={"search_name": "error_spike", "triggered_count": 50})])
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"


def test_app_log_drops_info():
    from app.nanoagents.app_log import filter
    decisions = filter([_sig("splunk_info_alert", severity="info", resource_kind="SplunkAlert")])
    assert len(decisions) == 1
    assert decisions[0].outcome == "drop"


def test_app_log_ignores_non_splunk():
    from app.nanoagents.app_log import filter
    decisions = filter([_sig("pod_crashloop")])
    assert len(decisions) == 0


# === AlertAgent ===

def test_alert_suppresses_false_positive():
    from app.nanoagents.alert_agent import filter
    decisions = filter([_sig("alert_warning", resource_name="InsightsRecommendationActive",
                             evidence={"alertname": "InsightsRecommendationActive"})])
    assert len(decisions) == 1
    assert decisions[0].outcome == "suppress"


def test_alert_escalates_critical():
    from app.nanoagents.alert_agent import filter
    decisions = filter([_sig("alert_critical", resource_name="etcdMembersDown",
                             evidence={"alertname": "etcdMembersDown", "summary": "etcd down"})])
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"


def test_alert_drops_info():
    from app.nanoagents.alert_agent import filter
    decisions = filter([_sig("alert_info", severity="info", resource_name="SomeInfo",
                             evidence={"alertname": "SomeInfo"})])
    assert len(decisions) == 1
    assert decisions[0].outcome == "drop"


# === SecurityAuditAgent ===

def test_security_escalates_rbac_denial():
    from app.nanoagents.security_audit import filter
    decisions = filter([_sig("alert_warning", severity="high", resource_name="rbac-check",
                             evidence={"description": "RBAC denied access to pods"})])
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"
    assert decisions[0].reason_code == "security_escalation"


def test_security_suppresses_noisy_sa():
    from app.nanoagents.security_audit import filter
    decisions = filter([_sig("alert_warning", resource_name="search-serviceaccount",
                             evidence={"description": "RBAC denied for search-serviceaccount"})])
    assert len(decisions) == 1
    assert decisions[0].outcome == "suppress"


# === ProvisioningAgent ===

def test_provisioning_drops_lifecycle():
    from app.nanoagents.provisioning import filter
    decisions = filter([_sig("event_successfulcreate", namespace="babylon-sandbox-api")])
    assert len(decisions) == 1
    assert decisions[0].outcome == "drop"


def test_provisioning_escalates_failure():
    from app.nanoagents.provisioning import filter
    decisions = filter([_sig("event_backofflimitexceeded", namespace="babylon-sandbox-api")])
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"


def test_provisioning_ignores_non_babylon():
    from app.nanoagents.provisioning import filter
    decisions = filter([_sig("event_backofflimitexceeded", namespace="production")])
    assert len(decisions) == 0


# === NetworkAgent ===

def test_network_escalates_migration_failure():
    from app.nanoagents.network import filter
    decisions = filter([_sig("event_failedmigration", namespace="icinga")])
    assert len(decisions) == 1
    assert decisions[0].outcome == "escalate"


def test_network_suppresses_migration_backoff():
    from app.nanoagents.network import filter
    decisions = filter([_sig("event_migrationbackoff", namespace="rcb", severity="medium")])
    assert len(decisions) == 1
    assert decisions[0].outcome == "suppress"


def test_network_keeps_metallb():
    from app.nanoagents.network import filter
    decisions = filter([_sig("event_unhealthy", namespace="metallb-system", severity="medium")])
    assert len(decisions) == 1
    assert decisions[0].outcome == "keep"
