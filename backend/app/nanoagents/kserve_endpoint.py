"""Detects model endpoint not ready."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "KServeEndpointAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type == "kserve_not_ready":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="model_endpoint_not_ready",
                evidence={"resource_name": s.resource_name, "namespace": s.namespace},
            ))
    return decisions
