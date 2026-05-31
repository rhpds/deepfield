"""Suppresses known short-lived startup transients AND high-volume namespace noise.

Two suppression strategies:
1. Transient: pod_pending, pvc_pending within 120s window (startup noise)
2. Namespace dampening: if a namespace+signal_type combo has fired >10 times
   in 10 minutes, suppress further signals of that type from that namespace.
"""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "TransientSuppressorAgent"

TRANSIENT_TYPES = {"pod_pending", "pvc_pending"}
TRANSIENT_WINDOW_SECONDS = 120

DAMPEN_THRESHOLD = 10
DAMPEN_WINDOW_SECONDS = 600


def filter(signals: List[NormalizedSignal], window_seconds: float = TRANSIENT_WINDOW_SECONDS) -> List[FilterDecision]:
    decisions = []
    seen: dict[str, float] = {}
    ns_counts: dict[str, list] = {}

    for s in signals:
        # Strategy 1: Transient suppression
        if s.signal_type in TRANSIENT_TYPES:
            key = f"{s.cluster_id}:{s.namespace}:{s.resource_name}:{s.signal_type}"
            ts = s.timestamp.timestamp()

            if key in seen and (ts - seen[key]) < window_seconds:
                decisions.append(FilterDecision(
                    signal_id=s.signal_id, filter_name=name, outcome="suppress",
                    reason_code="transient_within_window",
                    evidence={"window_seconds": window_seconds, "signal_type": s.signal_type},
                ))
                continue
            seen[key] = ts

        # Strategy 2: Namespace dampening for high-volume signal types
        ns_key = f"{s.namespace}:{s.signal_type}"
        ts = s.timestamp.timestamp()
        if ns_key not in ns_counts:
            ns_counts[ns_key] = []
        ns_counts[ns_key] = [t for t in ns_counts[ns_key] if ts - t < DAMPEN_WINDOW_SECONDS]
        ns_counts[ns_key].append(ts)

        if len(ns_counts[ns_key]) > DAMPEN_THRESHOLD:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="namespace_dampened",
                evidence={
                    "namespace": s.namespace,
                    "signal_type": s.signal_type,
                    "count_in_window": len(ns_counts[ns_key]),
                    "threshold": DAMPEN_THRESHOLD,
                },
            ))

    return decisions
