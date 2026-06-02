"""Suppresses known short-lived startup transients AND high-volume namespace noise.

Two suppression strategies:
1. Transient: pod_pending, pvc_pending within 120s window (startup noise)
2. Namespace dampening: if a namespace+signal_type combo has fired >10 times
   in 10 minutes, suppress further signals of that type from that namespace.

State persists across batches via module-level dicts.
"""

from typing import Dict, List

from app.domain.models import FilterDecision, NormalizedSignal

name = "TransientSuppressorAgent"

TRANSIENT_TYPES = {"pod_pending", "pvc_pending"}
TRANSIENT_WINDOW_SECONDS = 120

DAMPEN_THRESHOLD = 10
DAMPEN_WINDOW_SECONDS = 600

_transient_seen: Dict[str, float] = {}
_ns_counts: Dict[str, list] = {}


def reset_state():
    """Clear persistent state — used by tests."""
    _transient_seen.clear()
    _ns_counts.clear()


def filter(signals: List[NormalizedSignal], window_seconds: float = TRANSIENT_WINDOW_SECONDS,
           cluster_profile=None) -> List[FilterDecision]:
    decisions = []

    for s in signals:
        # Strategy 1: Transient suppression
        if s.signal_type in TRANSIENT_TYPES:
            key = f"{s.cluster_id}:{s.namespace}:{s.resource_name}:{s.signal_type}"
            ts = s.timestamp.timestamp()

            if key in _transient_seen and (ts - _transient_seen[key]) < window_seconds:
                decisions.append(FilterDecision(
                    signal_id=s.signal_id, filter_name=name, outcome="suppress",
                    reason_code="transient_within_window",
                    evidence={"window_seconds": window_seconds, "signal_type": s.signal_type},
                ))
                continue
            _transient_seen[key] = ts

        # Strategy 2: Namespace dampening for high-volume signal types
        ns_key = f"{s.namespace}:{s.signal_type}"
        ts = s.timestamp.timestamp()
        if ns_key not in _ns_counts:
            _ns_counts[ns_key] = []
        _ns_counts[ns_key] = [t for t in _ns_counts[ns_key] if ts - t < DAMPEN_WINDOW_SECONDS]
        _ns_counts[ns_key].append(ts)

        threshold = cluster_profile.get_dampen_threshold(s.namespace) if cluster_profile else DAMPEN_THRESHOLD
        if len(_ns_counts[ns_key]) > threshold:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="namespace_dampened",
                evidence={
                    "namespace": s.namespace,
                    "signal_type": s.signal_type,
                    "count_in_window": len(_ns_counts[ns_key]),
                    "threshold": threshold,
                },
            ))

    # Evict stale transient entries
    if len(_transient_seen) > 50000:
        cutoff = max(_transient_seen.values()) - 3600
        stale = [k for k, v in _transient_seen.items() if v < cutoff]
        for k in stale:
            del _transient_seen[k]

    # Evict stale namespace counts
    if len(_ns_counts) > 10000:
        stale = [k for k, v in _ns_counts.items() if not v]
        for k in stale:
            del _ns_counts[k]

    return decisions
