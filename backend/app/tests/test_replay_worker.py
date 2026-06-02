"""Tests for Kafka replay worker — unit tests without Kafka dependency."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from uuid import uuid4


class TestReplayStore:
    def test_replay_store_no_historical_load(self):
        from app.session.signal_store import ReplayStore
        store = ReplayStore(replay_id="test-replay")
        assert len(store.recent_signals) == 0
        assert len(store.agent_stats) == 0

    def test_replay_store_no_db_writes(self):
        from app.session.signal_store import ReplayStore
        store = ReplayStore(replay_id="test-replay")
        with patch("app.db.enqueue_write") as mock_write:
            store.add_signal({"signal_type": "pod_crashloop", "namespace": "test"})
            store.add_decision({"filter_name": "DedupeAgent", "outcome": "dedupe"})
            store.add_finding({"finding_type": "namespace_correlation"})
            store.add_inference({"model": "test", "task_type": "rca"})
            mock_write.assert_not_called()

    def test_replay_store_tracks_agent_stats(self):
        from app.session.signal_store import ReplayStore
        store = ReplayStore(replay_id="test-replay")
        store.add_decision({"filter_name": "DedupeAgent", "outcome": "dedupe"})
        store.add_decision({"filter_name": "DedupeAgent", "outcome": "dedupe"})
        store.add_decision({"filter_name": "EventClassifierAgent", "outcome": "escalate"})
        summary = store.get_agent_summary()
        assert summary["DedupeAgent"]["deduped"] == 2
        assert summary["EventClassifierAgent"]["escalated"] == 1


class TestReplayWorker:
    def test_replay_uses_separate_consumer_group(self):
        from app.workers.replay_worker import ReplayWorker
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        replay = ReplayWorker(from_timestamp_ms=now_ms - 3600000, to_timestamp_ms=now_ms)
        assert replay._worker.group_id.startswith("deepfield-replay-")
        assert replay.replay_id in replay._worker.group_id

    def test_replay_tracks_progress(self):
        from app.workers.replay_worker import ReplayWorker
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        replay = ReplayWorker(from_timestamp_ms=now_ms - 3600000, to_timestamp_ms=now_ms)
        assert replay.progress["status"] == "pending"
        assert replay.progress["processed"] == 0
        assert replay.progress["errors"] == 0
        assert "from_timestamp" in replay.progress
        assert "to_timestamp" in replay.progress

    def test_replay_stops_at_end_timestamp(self):
        from app.workers.replay_worker import ReplayWorker
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        replay = ReplayWorker(from_timestamp_ms=now_ms - 3600000, to_timestamp_ms=now_ms)
        assert replay.to_ts == now_ms

    def test_replay_on_complete_produces_results(self):
        from app.workers.replay_worker import ReplayWorker
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        replay = ReplayWorker(from_timestamp_ms=now_ms - 3600000, to_timestamp_ms=now_ms)
        replay.store.add_signal({"signal_type": "pod_crashloop"})
        replay.store.add_finding({"finding_type": "test"})
        replay._on_replay_complete()
        assert replay.progress["results"]["signal_count"] == 1
        assert replay.progress["results"]["finding_count"] == 1


class TestReplayManager:
    def test_manager_starts_replay(self):
        from app.workers.manager import WorkerManager
        mgr = WorkerManager()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        with patch("app.workers.replay_worker.ReplayWorker.start"):
            replay_id = mgr.start_replay(now_ms - 3600000, now_ms)
        assert replay_id in [r.replay_id for r in mgr._replays.values()]

    def test_manager_lists_replays(self):
        from app.workers.manager import WorkerManager
        mgr = WorkerManager()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        with patch("app.workers.replay_worker.ReplayWorker.start"):
            mgr.start_replay(now_ms - 3600000, now_ms)
        replays = mgr.list_replays()
        assert len(replays) == 1
