"""Detects active/failed/expired lab sessions."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "LaunchpadSessionAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type == "launchpad_lab_failed":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="lab_failed",
                evidence={"resource_name": s.resource_name, "labId": s.evidence.get("labId")},
            ))
        elif s.signal_type == "launchpad_lab_expired":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="lab_expired",
            ))
    return decisions
