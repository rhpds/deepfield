"""Deduplicates identical signals within a configurable time window.

State persists across batches via the shared _state dict so that signals
seen in batch N are still deduped in batch N+1.
"""

from typing import Dict, List

from app.domain.models import FilterDecision, NormalizedSignal

name = "DedupeAgent"

DEDUPE_WINDOW_SECONDS = 60

EXTENDED_WINDOW_TYPES = {
    "pod_crashloop": 300,
    "pod_imagepullbackoff": 300,
    "failed_scheduling": 600,
    "backoff_limit_exceeded": 300,
    "vm_migration_failed": 300,
    "invalid_configuration": 300,
    "node_pressure": 300,
}

_state: Dict[str, float] = {}


def reset_state():
    """Clear persistent state — used by tests."""
    _state.clear()


def filter(signals: List[NormalizedSignal], window_seconds: float = DEDUPE_WINDOW_SECONDS,
           cluster_profile=None) -> List[FilterDecision]:
    decisions = []

    for s in signals:
        key = f"{s.cluster_id}:{s.namespace}:{s.resource_kind}:{s.resource_name}:{s.signal_type}"
        ts = s.timestamp.timestamp()

        if cluster_profile:
            window = cluster_profile.get_dedup_window(s.signal_type)
        else:
            window = EXTENDED_WINDOW_TYPES.get(s.signal_type, window_seconds)

        if key in _state and (ts - _state[key]) < window:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="dedupe",
                reason_code="duplicate_within_window",
                evidence={"window_seconds": window, "duplicate_of_key": key},
            ))
        else:
            _state[key] = ts

    # Evict stale entries to prevent unbounded growth
    if len(_state) > 50000:
        cutoff = max(_state.values()) - 3600
        stale = [k for k, v in _state.items() if v < cutoff]
        for k in stale:
            del _state[k]

    return decisions
