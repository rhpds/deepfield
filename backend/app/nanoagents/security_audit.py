"""Classifies security and audit signals.
Escalates RBAC denials and unauthorized access, suppresses known service account churn."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "SecurityAuditAgent"

SECURITY_TYPES = {"splunk_audit_denied", "splunk_audit_anomaly", "alert_warning", "alert_critical"}

NOISY_SERVICE_ACCOUNTS = {
    "search-serviceaccount",
    "openshift-controller-manager-operator",
    "olm-operator-serviceaccount",
}

SECURITY_KEYWORDS = {"forbid", "denied", "unauthorized", "rbac", "permission"}


def filter(signals: List[NormalizedSignal], **kwargs) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        evidence = s.evidence or {}
        description = str(evidence.get("description", evidence.get("summary", ""))).lower()
        alertname = str(evidence.get("alertname", s.resource_name)).lower()

        is_security = (
            s.signal_type in {"splunk_audit_denied", "splunk_audit_anomaly"}
            or any(kw in description for kw in SECURITY_KEYWORDS)
            or any(kw in alertname for kw in SECURITY_KEYWORDS)
        )

        if not is_security:
            continue

        resource = s.resource_name
        if any(sa in resource for sa in NOISY_SERVICE_ACCOUNTS):
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="noisy_service_account",
                evidence={"resource": resource},
            ))
        elif s.severity in ("critical", "high"):
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="security_escalation",
                evidence={"alertname": alertname, "namespace": s.namespace, "description": description[:200]},
            ))
        else:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="security_event",
                evidence={"alertname": alertname, "namespace": s.namespace},
            ))
    return decisions
