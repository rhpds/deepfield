"""Detects high Kafka consumer lag."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "KafkaLagAgent"


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.signal_type == "kafka_lag_high":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="kafka_lag_elevated",
                evidence={"resource_name": s.resource_name, "lag": s.evidence.get("lag")},
            ))
    return decisions
