"""Classifies network-related signals — DNS failures, load balancer issues,
migration network events. Separates real network issues from transient migration noise."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "NetworkAgent"

NETWORK_NS = {"metallb-system", "openshift-dns", "openshift-ingress", "openshift-ovn-kubernetes", "openshift-multus"}

NETWORK_SIGNAL_TYPES = {
    "event_failedmigration", "event_migrationtargetpodunschedulable",
    "event_migrationbackoff", "event_failedupdate",
}

SUPPRESS_MIGRATION_TRANSIENT = {
    "event_migrationbackoff",
}

DNS_KEYWORDS = {"coredns", "dns", "resolve", "nxdomain"}


def filter(signals: List[NormalizedSignal], **kwargs) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        evidence = s.evidence or {}
        resource_lower = s.resource_name.lower()
        is_network = (
            s.namespace in NETWORK_NS
            or s.signal_type in NETWORK_SIGNAL_TYPES
            or any(kw in resource_lower for kw in DNS_KEYWORDS)
        )

        if not is_network:
            continue

        if s.signal_type in SUPPRESS_MIGRATION_TRANSIENT:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="migration_transient",
                evidence={"namespace": s.namespace, "signal_type": s.signal_type},
            ))
        elif s.signal_type in {"event_failedmigration", "event_migrationtargetpodunschedulable"}:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="migration_failure",
                evidence={"namespace": s.namespace, "resource": s.resource_name},
            ))
        elif s.namespace == "metallb-system" and s.severity == "medium":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="metallb_event",
                evidence={"namespace": s.namespace},
            ))
        elif s.severity in ("high", "critical"):
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="network_failure",
                evidence={"namespace": s.namespace, "signal_type": s.signal_type},
            ))
        else:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="network_event",
                evidence={"namespace": s.namespace},
            ))
    return decisions
