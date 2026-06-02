"""Worker manager — starts/stops all Kafka consumer workers."""

import logging
from typing import Optional

from app.workers.nano_agent_worker import NanoAgentWorker
from app.workers.correlation_worker import CorrelationWorker
from app.workers.inference_worker import InferenceWorker

logger = logging.getLogger("deepfield.workers")

_manager: Optional["WorkerManager"] = None


class WorkerManager:
    def __init__(self, client=None, store=None, cluster_profile=None):
        self.nano = NanoAgentWorker(cluster_profile=cluster_profile, store=store)
        self.correlation = CorrelationWorker(store=store)
        self.inference = InferenceWorker(client=client, store=store)
        self._workers = [self.nano, self.correlation, self.inference]

    def start_all(self):
        for w in self._workers:
            w.start()
        logger.info("All Kafka workers started (%d workers)", len(self._workers))

    def stop_all(self):
        for w in self._workers:
            w.stop()
        logger.info("All Kafka workers stopped")

    def stats(self) -> dict:
        return {
            "workers": [w.stats for w in self._workers],
            "total_processed": sum(w._messages_processed for w in self._workers),
            "total_errors": sum(w._errors for w in self._workers),
        }


def get_worker_manager() -> Optional["WorkerManager"]:
    return _manager


def start_workers(client=None, store=None, cluster_profile=None) -> "WorkerManager":
    global _manager
    if _manager:
        return _manager
    _manager = WorkerManager(client=client, store=store, cluster_profile=cluster_profile)
    _manager.start_all()
    return _manager


def stop_workers():
    global _manager
    if _manager:
        _manager.stop_all()
        _manager = None
