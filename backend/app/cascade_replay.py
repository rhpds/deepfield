"""Historical replay — feeds Postgres signals through the cascade to bootstrap knowledge.

Processes historical signals as if they were live, but in bulk.
The cascade discovers patterns, phi-4 validates, agents activate.
After replay, the cascade starts live with full historical knowledge.

Usage:
    POST /api/v1/session/cascade/replay
    {"batch_size": 1000, "limit": 100000, "phi4_enabled": false}
"""

import logging
import os
import time
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://deepfield:deepfield2026x@deepfield-postgres:5432/deepfield")


class HistoricalReplay:
    def __init__(self, batch_size: int = 1000, limit: Optional[int] = None, phi4_sample_rate: float = 0.1):
        self.batch_size = batch_size
        self.limit = limit
        self.phi4_sample_rate = phi4_sample_rate  # classify 10% with phi-4
        self.status = "idle"
        self.progress = {
            "total_available": 0,
            "processed": 0,
            "batches": 0,
            "elapsed_seconds": 0,
            "signals_per_second": 0,
            "patterns_discovered": 0,
            "agents_activated": 0,
            "compression_ratio": 0,
        }

    def run(self, cascade_bridge, background: bool = True):
        """Run the replay. If background=True, runs in a thread."""
        if self.status == "running":
            return {"error": "Replay already running"}

        if background:
            threading.Thread(target=self._replay, args=(cascade_bridge,), daemon=True).start()
            return {"status": "started", "batch_size": self.batch_size, "limit": self.limit}
        else:
            return self._replay(cascade_bridge)

    def _replay(self, cascade_bridge):
        self.status = "running"
        t0 = time.monotonic()

        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL)
            conn.set_session(readonly=True)

            # Get total count
            cur = conn.cursor()
            cur.execute("SELECT reltuples::bigint FROM pg_class WHERE relname = 'signals'")
            self.progress["total_available"] = cur.fetchone()[0]
            cur.close()

            # Stream signals in batches using server-side cursor
            cur = conn.cursor("replay_cursor")
            cur.itersize = self.batch_size

            query = "SELECT id, cluster, namespace, resource_kind, resource_name, signal_type, severity, evidence FROM signals ORDER BY created_at"
            if self.limit:
                query += f" LIMIT {self.limit}"

            cur.execute(query)
            log.info("REPLAY STARTED: batch_size=%d limit=%s", self.batch_size, self.limit)

            batch = []
            batch_num = 0

            for row in cur:
                # Convert DB row to NormalizedSignal-like object
                signal = _RowSignal(
                    signal_id=row[0],
                    cluster_id=row[1] or "",
                    namespace=row[2] or "",
                    resource_kind=row[3] or "",
                    resource_name=row[4] or "",
                    signal_type=row[5] or "",
                    severity=row[6] or "info",
                    evidence=row[7] or {},
                    labels={},
                )
                batch.append(signal)

                if len(batch) >= self.batch_size:
                    batch_num += 1
                    # Process batch through cascade (no deepfield decisions to compare)
                    cascade_bridge.process(batch, [])

                    self.progress["processed"] += len(batch)
                    self.progress["batches"] = batch_num
                    elapsed = time.monotonic() - t0
                    self.progress["elapsed_seconds"] = round(elapsed)
                    self.progress["signals_per_second"] = round(self.progress["processed"] / elapsed) if elapsed > 0 else 0
                    self.progress["compression_ratio"] = round(cascade_bridge.stats.compression_ratio * 100, 1)
                    self.progress["agents_activated"] = len(cascade_bridge._activated_types)

                    if batch_num % 100 == 0:
                        log.info("REPLAY: %d signals, %d batches, %.0f sig/s, %.1f%% compression, %d activated",
                                 self.progress["processed"], batch_num,
                                 self.progress["signals_per_second"],
                                 self.progress["compression_ratio"],
                                 self.progress["agents_activated"])

                    batch = []

            # Process remaining
            if batch:
                cascade_bridge.process(batch, [])
                self.progress["processed"] += len(batch)

            cur.close()
            conn.close()

            elapsed = time.monotonic() - t0
            self.progress["elapsed_seconds"] = round(elapsed)
            self.progress["signals_per_second"] = round(self.progress["processed"] / elapsed) if elapsed > 0 else 0
            self.progress["compression_ratio"] = round(cascade_bridge.stats.compression_ratio * 100, 1)
            self.progress["agents_activated"] = len(cascade_bridge._activated_types)

            # Save state after replay
            cascade_bridge._save_state()

            self.status = "completed"
            log.info("REPLAY COMPLETE: %d signals in %.0fs (%.0f sig/s), %.1f%% compression, %d agents",
                     self.progress["processed"], elapsed,
                     self.progress["signals_per_second"],
                     self.progress["compression_ratio"],
                     self.progress["agents_activated"])

            return self.progress

        except Exception as e:
            self.status = f"error: {str(e)[:100]}"
            log.error("REPLAY ERROR: %s", e)
            return {"error": str(e)}

    def get_status(self):
        return {
            "status": self.status,
            **self.progress,
        }


class _RowSignal:
    """Minimal signal object that matches NormalizedSignal interface for cascade_bridge.process()."""
    def __init__(self, signal_id, cluster_id, namespace, resource_kind, resource_name,
                 signal_type, severity, evidence, labels):
        self.signal_id = signal_id
        self.cluster_id = cluster_id
        self.namespace = namespace
        self.resource_kind = resource_kind
        self.resource_name = resource_name
        self.signal_type = signal_type
        self.severity = severity
        self.evidence = evidence if isinstance(evidence, dict) else {}
        self.labels = labels or {}
