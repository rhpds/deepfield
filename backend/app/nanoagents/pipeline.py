"""Chains nano-agents into a filter pipeline."""

from typing import List
import importlib

from app.domain.models import FilterDecision, NormalizedSignal

AGENT_MODULES = [
    "app.nanoagents.failure_classifier",
    "app.nanoagents.event_classifier",
    "app.nanoagents.pod_health",
    "app.nanoagents.route_health",
    "app.nanoagents.pvc_health",
    "app.nanoagents.node_pressure",
    "app.nanoagents.namespace_quota",
    "app.nanoagents.kserve_endpoint",
    "app.nanoagents.kafka_lag",
    "app.nanoagents.launchpad_session",
    "app.nanoagents.stargate_evaluation",
    "app.nanoagents.transient_suppressor",
    "app.nanoagents.dedupe",
]


def run_pipeline(signals: List[NormalizedSignal], cluster_profile=None) -> dict:
    all_decisions: List[FilterDecision] = []
    suppressed_ids: set = set()
    deduped_ids: set = set()

    for module_path in AGENT_MODULES:
        module = importlib.import_module(module_path)
        if cluster_profile and module_path in (
            "app.nanoagents.dedupe", "app.nanoagents.transient_suppressor"
        ):
            decisions = module.filter(signals, cluster_profile=cluster_profile)
        else:
            decisions = module.filter(signals)
        all_decisions.extend(decisions)

        for d in decisions:
            if d.outcome == "suppress":
                suppressed_ids.add(d.signal_id)
            elif d.outcome == "dedupe":
                deduped_ids.add(d.signal_id)

    decided_ids = {d.signal_id for d in all_decisions}
    escalated = [d for d in all_decisions if d.outcome == "escalate"]
    kept = [d for d in all_decisions if d.outcome == "keep"]
    dropped_ids = suppressed_ids | deduped_ids

    remaining = [s for s in signals if s.signal_id not in dropped_ids]
    info_dropped = [s for s in signals if s.severity == "info" and s.signal_id not in decided_ids]

    return {
        "total_signals": len(signals),
        "decisions": all_decisions,
        "escalated": escalated,
        "kept": kept,
        "suppressed_count": len(suppressed_ids),
        "deduped_count": len(deduped_ids),
        "info_dropped_count": len(info_dropped),
        "remaining_signals": remaining,
        "retained_count": len(remaining),
    }
