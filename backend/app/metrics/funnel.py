"""Signal funnel aggregation."""

from dataclasses import dataclass
from typing import List

from app.domain.models import FilterDecision, NormalizedSignal, CandidateFinding, ReasoningTask


@dataclass
class SignalFunnel:
    raw_signals_received: int
    normalized_signals: int
    dropped_signals: int
    deduped_signals: int
    suppressed_transients: int
    retained_signals: int
    correlated_findings: int
    reasoning_tasks_created: int
    final_insights_created: int
    signal_reduction_percent: float
    llm_escalation_rate_percent: float
    reasoning_compression_ratio: float


def compute_funnel(
    raw_count: int,
    normalized: List[NormalizedSignal],
    decisions: List[FilterDecision],
    findings: List[CandidateFinding],
    tasks: List[ReasoningTask],
    insights_count: int = 0,
) -> SignalFunnel:
    deduped = sum(1 for d in decisions if d.outcome == "dedupe")
    suppressed = sum(1 for d in decisions if d.outcome == "suppress")
    dropped = sum(1 for d in decisions if d.outcome == "drop")
    info_dropped = sum(1 for s in normalized if s.severity == "info") - sum(
        1 for d in decisions if d.outcome == "escalate"
        and any(s.signal_id == d.signal_id and s.severity == "info" for s in normalized)
    )

    total_dropped = dropped + deduped + suppressed + max(0, info_dropped)
    retained = len(normalized) - total_dropped
    reasoning_count = len(tasks)

    reduction = (total_dropped / raw_count * 100) if raw_count > 0 else 0
    escalation = (reasoning_count / raw_count * 100) if raw_count > 0 else 0
    compression = (raw_count / reasoning_count) if reasoning_count > 0 else float("inf")

    return SignalFunnel(
        raw_signals_received=raw_count,
        normalized_signals=len(normalized),
        dropped_signals=total_dropped,
        deduped_signals=deduped,
        suppressed_transients=suppressed,
        retained_signals=retained,
        correlated_findings=len(findings),
        reasoning_tasks_created=reasoning_count,
        final_insights_created=insights_count,
        signal_reduction_percent=round(reduction, 2),
        llm_escalation_rate_percent=round(escalation, 4),
        reasoning_compression_ratio=round(compression, 1),
    )
