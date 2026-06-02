"""Kafka consumer: filtered signals → correlation → findings."""

import logging
import time
from collections import deque
from datetime import datetime, timezone
from uuid import UUID

from app.workers.base import KafkaWorker

logger = logging.getLogger("deepfield.workers.correlation")

_BUFFER_MAX = 500
_COOLDOWN_SECS = 60


class CorrelationWorker(KafkaWorker):
    topic = "deepfield-filtered-signals"
    group_id = "deepfield-correlation"

    def __init__(self, store=None):
        super().__init__()
        self._buffer: deque = deque(maxlen=_BUFFER_MAX)
        self._finding_cooldown: dict = {}
        self._store = store

    def process(self, message: dict) -> None:
        from app.domain.models import NormalizedSignal
        from app.correlation.engine import correlate
        from app.integrations.kafka_publisher import publish_finding

        sig = NormalizedSignal(
            signal_id=message.get("signal_id", "00000000-0000-0000-0000-000000000000"),
            cluster_id=message.get("cluster_id", "00000000-0000-0000-0000-000000000000"),
            namespace=message.get("namespace", ""),
            resource_kind=message.get("resource_kind", ""),
            resource_name=message.get("resource_name", ""),
            signal_type=message.get("signal_type", ""),
            severity=message.get("severity", "medium"),
            confidence=message.get("confidence", 0.5),
            evidence=message.get("evidence", {}),
            timestamp=message.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )

        self._buffer.append(sig)

        if len(self._buffer) < 2:
            return

        findings = correlate(list(self._buffer))
        now = time.monotonic()

        for f in findings:
            key = f"{f.finding_type}:{','.join(sorted(f.namespaces))}"
            last_seen = self._finding_cooldown.get(key)
            if last_seen is not None and now - last_seen < _COOLDOWN_SECS:
                continue
            self._finding_cooldown[key] = now

            finding_dict = {
                "finding_id": str(f.finding_id),
                "finding_type": f.finding_type,
                "severity": f.severity,
                "summary": f.summary,
                "namespaces": f.namespaces,
                "clusters": [str(c) for c in f.clusters],
                "signal_ids": [str(s) for s in f.signal_ids],
                "signal_count": len(f.signal_ids),
                "evidence": f.evidence,
            }

            if self._store:
                self._store.add_finding(finding_dict)

            publish_finding(finding_dict)
            logger.info("Finding published: %s in %s (%d signals)",
                        f.finding_type, f.namespaces, len(f.signal_ids))
