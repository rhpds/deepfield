"""Tests for the StreamingSession process loop.

Validates that the streaming session correctly processes synthetic signals,
produces snapshots, drains its queue, and stops cleanly.
"""

import time

from app.session.streaming_session import create_streaming_session
from app.inference.client import MockInferenceClient


def test_synthetic_processes_continuously():
    """Start session, sleep 3s, verify raw_signals > 0."""
    client = MockInferenceClient(seed=100)
    session = create_streaming_session(client=client, seed=100)
    session.update_params(clusters=2, failure_rate=0.05, signals_per_second=50)
    session.start()
    time.sleep(3)
    session.stop()

    state = session.get_state()
    assert state["totals"]["raw_signals"] > 0


def test_snapshots_tick():
    """Start session, sleep 4s, verify snapshots >= 1."""
    client = MockInferenceClient(seed=200)
    session = create_streaming_session(client=client, seed=200)
    session.update_params(clusters=2, failure_rate=0.05, signals_per_second=50)
    session.start()
    time.sleep(4)
    session.stop()

    state = session.get_state()
    assert len(state["snapshots"]) >= 1


def test_queue_drains():
    """Start session, sleep 2s, verify queue_depth is near zero.

    The emitter and processor stop concurrently when stop() is called,
    so a small residual queue (< 50 signals from the last emitter batch)
    is acceptable.
    """
    client = MockInferenceClient(seed=300)
    session = create_streaming_session(client=client, seed=300)
    session.update_params(clusters=2, failure_rate=0.05, signals_per_second=50)
    session.start()
    time.sleep(2)
    session.stop()
    time.sleep(0.5)

    state = session.get_state()
    # Processor drains 500 signals per tick; residual is at most one emitter batch
    assert state["queue_depth"] < 50


def test_stop_cleanly():
    """Start, sleep 1s, stop, verify status=stopped."""
    client = MockInferenceClient(seed=400)
    session = create_streaming_session(client=client, seed=400)
    session.update_params(clusters=2, failure_rate=0.05, signals_per_second=50)
    session.start()
    time.sleep(1)
    session.stop()

    state = session.get_state()
    assert state["status"] == "stopped"
