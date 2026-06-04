"""Filters AlertManager/Prometheus alerts.
Suppresses known false positives, escalates critical infrastructure alerts."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "AlertAgent"

ALERT_TYPES = {"alert_critical", "alert_warning", "alert_info"}

SUPPRESS_ALERTS = {
    "InsightsRecommendationActive",
    "UpdateAvailable",
    "ClusterNotUpgradeable",
    "SamplesTBRInaccessibleOnBoot",
    "CDIStorageProfilesIncomplete",
    "PrometheusNotIngestingSamples",
}

ESCALATE_ALERTS = {
    "SystemMemoryExceedsReservation",
    "NodeFilesystemAlmostOutOfSpace",
    "NodeFilesystemSpaceFillingUp",
    "KubeMemoryOvercommit",
    "KubeCPUOvercommit",
    "etcdHighNumberOfLeaderChanges",
    "etcdMembersDown",
    "KubeAPIDown",
    "KubeControllerManagerDown",
    "KubeSchedulerDown",
    "MCDDrainError",
    "ClusterOperatorDegraded",
}


def filter(signals: List[NormalizedSignal], **kwargs) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type not in ALERT_TYPES:
            continue

        evidence = s.evidence or {}
        alertname = str(evidence.get("alertname", s.resource_name))

        if alertname in SUPPRESS_ALERTS:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="known_false_positive",
                evidence={"alertname": alertname},
            ))
        elif alertname in ESCALATE_ALERTS or s.signal_type == "alert_critical":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="critical_alert",
                evidence={
                    "alertname": alertname,
                    "summary": str(evidence.get("summary", ""))[:200],
                    "namespace": s.namespace,
                },
            ))
        elif s.signal_type == "alert_info":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="drop",
                reason_code="info_alert",
                evidence={"alertname": alertname},
            ))
        else:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="warning_alert",
                evidence={"alertname": alertname, "namespace": s.namespace},
            ))
    return decisions
