"""Detects routes with no endpoints or unhealthy status."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "RouteHealthAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.resource_kind != "Route":
            continue
        if s.signal_type == "route_unhealthy":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="route_unhealthy",
                evidence={"resource_name": s.resource_name, "namespace": s.namespace},
            ))
    return decisions
