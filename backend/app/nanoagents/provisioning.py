"""Classifies Babylon/Anarchy provisioning lifecycle signals.
Suppresses normal sandbox churn, escalates provisioning failures."""

from fnmatch import fnmatch
from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "ProvisioningAgent"

PROVISIONING_NS_PATTERNS = [
    "babylon-*", "poolboy", "babylon-sandbox-api",
    "sandbox-*", "anarchy-*",
]

LIFECYCLE_TYPES = {"event_successfulcreate", "event_successfuldelete", "event_created"}

FAILURE_REASONS = {
    "event_backofflimitexceeded", "event_failed", "event_failedcreate",
    "job_failed", "backoff_limit_exceeded",
}


def _is_provisioning_ns(namespace: str) -> bool:
    return any(fnmatch(namespace, pat) for pat in PROVISIONING_NS_PATTERNS)


def filter(signals: List[NormalizedSignal], **kwargs) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if not _is_provisioning_ns(s.namespace):
            continue

        if s.signal_type in LIFECYCLE_TYPES:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="drop",
                reason_code="normal_provisioning_lifecycle",
                evidence={"namespace": s.namespace},
            ))
        elif s.signal_type in FAILURE_REASONS:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="provisioning_failure",
                evidence={
                    "signal_type": s.signal_type,
                    "namespace": s.namespace,
                    "resource": s.resource_name,
                },
            ))
        elif s.severity in ("info", "low"):
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="drop",
                reason_code="sandbox_noise",
                evidence={"namespace": s.namespace},
            ))
        else:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="provisioning_signal",
                evidence={"namespace": s.namespace, "signal_type": s.signal_type},
            ))
    return decisions
