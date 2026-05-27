"""Suppresses known short-lived startup/provisioning transients."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "TransientSuppressorAgent"

TRANSIENT_TYPES = {"pod_pending", "pvc_pending"}
TRANSIENT_WINDOW_SECONDS = 120


def filter(signals: List[NormalizedSignal], window_seconds: float = TRANSIENT_WINDOW_SECONDS) -> List[FilterDecision]:
    decisions = []
    seen: dict[str, float] = {}

    for s in signals:
        if s.signal_type not in TRANSIENT_TYPES:
            continue

        key = f"{s.cluster_id}:{s.namespace}:{s.resource_name}:{s.signal_type}"
        ts = s.timestamp.timestamp()

        if key in seen and (ts - seen[key]) < window_seconds:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="transient_within_window",
                evidence={"window_seconds": window_seconds, "signal_type": s.signal_type},
            ))
        else:
            seen[key] = ts

    return decisions
