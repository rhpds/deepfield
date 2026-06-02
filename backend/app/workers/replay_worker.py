"""Kafka replay worker — replays historical messages through updated pipeline rules.

Uses a separate consumer group (deepfield-replay-{id}) so live processing is unaffected.
Results go to a ReplayStore (in-memory only, no DB writes).
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.session.signal_store import ReplayStore
from app.workers.nano_agent_worker import NanoAgentWorker

logger = logging.getLogger("deepfield.workers.replay")


class ReplayWorker:
    def __init__(self, from_timestamp_ms: int, to_timestamp_ms: int,
                 cluster_profile=None, replay_id: str = None):
        self.replay_id = replay_id or str(uuid4())
        self.from_ts = from_timestamp_ms
        self.to_ts = to_timestamp_ms
        self.store = ReplayStore(replay_id=self.replay_id)
        self._worker = NanoAgentWorker(cluster_profile=cluster_profile, store=self.store)
        self._worker.group_id = f"deepfield-replay-{self.replay_id}"
        self._worker.auto_offset_reset = "earliest"
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.progress = {
            "replay_id": self.replay_id,
            "status": "pending",
            "processed": 0,
            "errors": 0,
            "from_timestamp": datetime.fromtimestamp(from_timestamp_ms / 1000, tz=timezone.utc).isoformat(),
            "to_timestamp": datetime.fromtimestamp(to_timestamp_ms / 1000, tz=timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
        }

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.progress["status"] = "running"
        self.progress["started_at"] = datetime.now(timezone.utc).isoformat()
        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f"replay-{self.replay_id[:8]}",
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            from kafka import KafkaConsumer
            import json

            consumer = KafkaConsumer(
                "deepfield-raw-signals",
                bootstrap_servers=self._worker._get_bootstrap() if hasattr(self._worker, '_get_bootstrap') else _get_bootstrap_servers(),
                group_id=self._worker.group_id,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                consumer_timeout_ms=5000,
            )

            consumer.poll(timeout_ms=1000)
            partitions = consumer.assignment()
            offsets = consumer.offsets_for_times(
                {tp: self.from_ts for tp in partitions}
            )
            for tp, offset_and_ts in (offsets or {}).items():
                if offset_and_ts is not None:
                    consumer.seek(tp, offset_and_ts.offset)

            while not self._stop.is_set():
                records = consumer.poll(timeout_ms=2000)
                if not records:
                    self.progress["status"] = "completed"
                    break
                for tp, messages in records.items():
                    for msg in messages:
                        if self._stop.is_set():
                            break
                        if msg.timestamp and msg.timestamp > self.to_ts:
                            self.progress["status"] = "completed"
                            self._stop.set()
                            break
                        try:
                            self._worker.process(msg.value)
                            self.progress["processed"] += 1
                        except Exception:
                            self.progress["errors"] += 1

            consumer.close(autocommit=False)

        except ImportError:
            logger.debug("kafka-python not installed — replay disabled")
            self.progress["status"] = "error"
        except Exception as e:
            logger.warning("Replay %s failed: %s", self.replay_id[:8], str(e)[:100])
            self.progress["status"] = "error"

        self.progress["completed_at"] = datetime.now(timezone.utc).isoformat()
        if self.progress["status"] == "running":
            self.progress["status"] = "completed"

        self._on_replay_complete()

    def _on_replay_complete(self):
        agent_summary = self.store.get_agent_summary()
        total_evals = sum(a.get("total_evaluated", 0) for a in agent_summary.values())
        total_deduped = sum(a.get("deduped", 0) for a in agent_summary.values())
        total_suppressed = sum(a.get("suppressed", 0) for a in agent_summary.values())

        self.progress["results"] = {
            "agent_summary": agent_summary,
            "signal_count": len(self.store.recent_signals),
            "finding_count": len(self.store.recent_findings),
            "decision_count": len(self.store.recent_decisions),
        }

        try:
            from app.analysis.evaluator import evaluate_pipeline
            from app.analysis.rubric_history import get_rubric_history

            dedup_rate = total_deduped / max(total_evals, 1)
            suppress_rate = total_suppressed / max(total_evals, 1)
            compression = total_evals / max(len(self.store.recent_findings), 1)

            evaluation = evaluate_pipeline(
                cluster_id="replay",
                compression_ratio=compression,
                dedup_rate=dedup_rate,
                suppress_rate=suppress_rate,
                unique_finding_types=len({f.get("finding_type") for f in self.store.recent_findings}),
                json_compliance_rate=0.9,
                taxonomy_match_rate=0.8,
                inconsistent_names_rate=0.0,
                unclassified_rate=0.0,
                error_rate=0.0,
                avg_rca_tokens=0,
                avg_micro_tokens=0,
                unique_root_causes=0,
                namespaces_monitored=len({s.get("namespace") for s in self.store.recent_signals}),
                active_agents=len(agent_summary),
                signal_type_diversity=len({s.get("signal_type") for s in self.store.recent_signals}),
                critical_signals_today=sum(1 for s in self.store.recent_signals if s.get("severity") in ("high", "critical")),
                new_types_suppressed=0,
                cross_resource_dedup=0,
                critical_deduped=0,
            )
            self.progress["evaluation"] = evaluation
            get_rubric_history().record("replay", evaluation, source="replay", source_id=self.replay_id)
        except Exception as e:
            logger.debug("Replay evaluation failed: %s", e)


def _get_bootstrap_servers():
    import os
    return os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS",
        "ecosystem-kafka-kafka-bootstrap.ecosystem-kafka.svc:9092",
    )
