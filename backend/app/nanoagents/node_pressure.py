"""Detects memory/cpu/disk pressure signals."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "NodePressureAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type == "node_pressure":
            condition = s.evidence.get("condition", "unknown")
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code=f"node_pressure_{condition}".lower(),
                evidence={"resource_name": s.resource_name, "condition": condition},
            ))
    return decisions
