"""Deduplicates identical signals within a configurable time window."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "DedupeAgent"

DEDUPE_WINDOW_SECONDS = 60


def filter(signals: List[NormalizedSignal], window_seconds: float = DEDUPE_WINDOW_SECONDS) -> List[FilterDecision]:
    decisions = []
    seen: dict[str, float] = {}

    for s in signals:
        key = f"{s.cluster_id}:{s.namespace}:{s.resource_kind}:{s.resource_name}:{s.signal_type}"
        ts = s.timestamp.timestamp()

        if key in seen and (ts - seen[key]) < window_seconds:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="dedupe",
                reason_code="duplicate_within_window",
                evidence={"window_seconds": window_seconds, "duplicate_of_key": key},
            ))
        else:
            seen[key] = ts

    return decisions
