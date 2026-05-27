"""Detects PVC pending or stuck."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "PVCHealthAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.resource_kind != "PersistentVolumeClaim":
            continue
        if s.signal_type == "pvc_pending":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="pvc_pending_stuck",
                evidence={"resource_name": s.resource_name, "namespace": s.namespace},
            ))
    return decisions
