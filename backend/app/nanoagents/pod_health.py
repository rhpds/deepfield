"""Detects crashloops, pending pods, image pull failures."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "PodHealthAgent"

ESCALATE_TYPES = {"pod_crashloop", "pod_imagepullbackoff"}
KEEP_TYPES = {"pod_pending"}


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.resource_kind != "Pod":
            continue
        if s.signal_type in ESCALATE_TYPES:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code=f"{s.signal_type}_detected",
                evidence={"signal_type": s.signal_type, "namespace": s.namespace},
            ))
        elif s.signal_type in KEEP_TYPES:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="pod_pending",
            ))
    return decisions
