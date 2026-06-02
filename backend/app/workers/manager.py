"""Worker manager — starts/stops all Kafka consumer workers."""

import logging
from typing import Dict, Optional

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
        self._cluster_profile = cluster_profile
        self._replays: Dict[str, "ReplayWorker"] = {}

    def start_all(self):
        for w in self._workers:
            w.start()
        logger.info("All Kafka workers started (%d workers)", len(self._workers))

    def stop_all(self):
        for w in self._workers:
            w.stop()
        logger.info("All Kafka workers stopped")

    def start_replay(self, from_timestamp_ms: int, to_timestamp_ms: int) -> str:
        from app.workers.replay_worker import ReplayWorker
        replay = ReplayWorker(
            from_timestamp_ms=from_timestamp_ms,
            to_timestamp_ms=to_timestamp_ms,
            cluster_profile=self._cluster_profile,
        )
        self._replays[replay.replay_id] = replay
        replay.start()
        return replay.replay_id

    def stop_replay(self, replay_id: str):
        replay = self._replays.get(replay_id)
        if replay:
            replay.stop()

    def get_replay(self, replay_id: str) -> Optional[dict]:
        replay = self._replays.get(replay_id)
        if not replay:
            return None
        return {**replay.progress, "results": replay.progress.get("results")}

    def list_replays(self) -> list:
        return [r.progress for r in self._replays.values()]

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
