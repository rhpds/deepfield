"""Detects quota exceeded or near limit."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "NamespaceQuotaAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type == "namespace_quota_exceeded":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="escalate",
                reason_code="quota_exceeded",
                evidence={"namespace": s.namespace, "resource": s.evidence.get("resource", "unknown")},
            ))
    return decisions
