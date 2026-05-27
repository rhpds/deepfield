"""Tests for SyntheticSession — decoupled from StreamingSession."""

import time

from app.session.synthetic_session import SyntheticSession
from app.inference.client import MockInferenceClient


def test_synthetic_session_starts_and_stops():
    client = MockInferenceClient(seed=42)
    session = SyntheticSession("test-1", client=client, seed=42)
    session.update_params(clusters=2, failure_rate=0.05, signals_per_second=50)
    session.start()
    time.sleep(1.0)
    session.stop()

    state = session.get_state()
    assert state["status"] == "stopped"
    assert state["totals"]["raw_signals"] > 0
    assert state["agent_log"] == []


def test_synthetic_session_metrics_update_on_success():
    client = MockInferenceClient(seed=42)
    session = SyntheticSession("test-2", client=client, seed=42)
    session.update_params(clusters=3, failure_rate=0.10, signals_per_second=200)
    session.start()
    time.sleep(2.0)
    session.stop()

    state = session.get_state()
    assert state["totals"]["inference_calls"] > 0
    assert state["metrics"]["avg_latency_ms"] > 0
    assert state["metrics"]["avg_tps"] > 0
    assert len(state["model_stats"]) > 0


def test_synthetic_session_has_no_store():
    session = SyntheticSession("test-3", seed=42)
    assert not hasattr(session, 'store')


def test_synthetic_session_get_state_shape():
    session = SyntheticSession("test-4", seed=42)
    state = session.get_state()
    assert "session_id" in state
    assert "metrics" in state
    assert "totals" in state
    assert "model_stats" in state
    assert "live_inference" in state
    assert "agent_log" in state
    assert "snapshots" in state
    assert "queue_depth" in state
