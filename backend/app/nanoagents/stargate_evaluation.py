"""Detects StarGate rubric evaluation pass/fail signals."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "StarGateEvaluationAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type == "stargate_stage_failed":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="stage_failed",
                evidence={"resource_name": s.resource_name, "failure_class": s.evidence.get("failure_class")},
            ))
        elif s.signal_type == "stargate_stage_passed":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="drop",
                reason_code="stage_passed",
            ))
    return decisions
