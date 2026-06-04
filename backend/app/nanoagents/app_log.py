"""Classifies application-level log signals from Splunk.
Suppresses known noise, escalates error spikes and crash patterns."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "AppLogAgent"

SPLUNK_TYPES = {
    "splunk_critical_alert", "splunk_high_alert", "splunk_medium_alert",
    "splunk_low_alert", "splunk_info_alert", "splunk_error_spike",
    "splunk_slow_response", "splunk_anomaly",
}

ESCALATE_TYPES = {"splunk_critical_alert", "splunk_high_alert", "splunk_error_spike"}
DROP_TYPES = {"splunk_info_alert"}

NOISY_SEARCHES = {"ocp_infra_errors"}


def filter(signals: List[NormalizedSignal], **kwargs) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type not in SPLUNK_TYPES:
            continue

        evidence = s.evidence or {}
        search_name = str(evidence.get("search_name", ""))
        triggered_count = int(evidence.get("triggered_count", 0))

        if search_name in NOISY_SEARCHES:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="known_noisy_search",
                evidence={"search_name": search_name},
            ))
        elif s.signal_type in ESCALATE_TYPES:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="app_error_escalation",
                evidence={
                    "search_name": search_name,
                    "triggered_count": triggered_count,
                    "namespace": s.namespace,
                },
            ))
        elif s.signal_type in DROP_TYPES:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="drop",
                reason_code="info_level_alert",
            ))
        else:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="app_log_classified",
                evidence={"search_name": search_name, "namespace": s.namespace},
            ))
    return decisions
