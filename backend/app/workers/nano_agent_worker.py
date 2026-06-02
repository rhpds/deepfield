"""Kafka consumer: raw signals → nano-agent pipeline → filtered signals."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from app.workers.base import KafkaWorker

logger = logging.getLogger("deepfield.workers.nano")


class NanoAgentWorker(KafkaWorker):
    topic = "deepfield-raw-signals"
    group_id = "deepfield-nano-agents"

    def __init__(self, cluster_profile=None, store=None):
        super().__init__()
        self._cluster_profile = cluster_profile
        self._store = store

    def process(self, message: dict) -> None:
        from app.domain.models import RawSignal, NormalizedSignal
        from app.normalizers.signal_normalizer import normalize_signal
        from app.nanoagents.pipeline import run_pipeline
        from app.routing.signal_router import route_signals
        from app.integrations.kafka_publisher import publish_filtered_signal

        raw = RawSignal(
            signal_id=message.get("signal_id", "00000000-0000-0000-0000-000000000000"),
            cluster_id=message.get("cluster_id", "00000000-0000-0000-0000-000000000000"),
            namespace=message.get("namespace", ""),
            resource_kind=message.get("resource_kind", ""),
            resource_name=message.get("resource_name", ""),
            source=message.get("source", ""),
            signal_type=message.get("signal_type", ""),
            raw_payload=message.get("raw_payload", {}),
            timestamp=message.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )

        normalized = normalize_signal(raw)

        pipeline_result = run_pipeline([normalized], cluster_profile=self._cluster_profile)
        if pipeline_result is None:
            return

        routing_result = route_signals([normalized], pipeline_result["decisions"])
        kept = routing_result["kept"]

        if self._store:
            for d in pipeline_result.get("decisions", []):
                self._store.add_decision({
                    "filter_name": d.filter_name, "outcome": d.outcome,
                    "reason": d.reason_code, "signal_id": str(d.signal_id)[:8],
                    "evidence": d.evidence,
                })

        for s in kept:
            publish_filtered_signal({
                "signal_id": str(s.signal_id),
                "cluster_id": str(s.cluster_id),
                "namespace": s.namespace,
                "resource_kind": s.resource_kind,
                "resource_name": s.resource_name,
                "signal_type": s.signal_type,
                "severity": s.severity,
                "confidence": s.confidence,
                "evidence": s.evidence,
                "source": getattr(s, "source", ""),
                "timestamp": s.timestamp.isoformat() if hasattr(s.timestamp, "isoformat") else str(s.timestamp),
            })
