"""TDD tests for signal store."""

from app.session.signal_store import SignalStore


def test_signal_store_captures_signals():
    store = SignalStore()
    store.add_signal({"signal_type": "pod_crashloop", "namespace": "test", "source": "live:infra01"})
    assert len(store.get_recent_signals()) == 1


def test_signal_store_captures_decisions():
    store = SignalStore()
    store.add_decision({"filter_name": "PodHealthAgent", "outcome": "escalate", "reason": "crashloop"})
    assert len(store.get_recent_decisions()) == 1
    stats = store.get_agent_summary()
    assert "PodHealthAgent" in stats
    assert stats["PodHealthAgent"]["escalated"] == 1


def test_signal_store_captures_inferences():
    store = SignalStore()
    store.add_inference({"model": "deepseek", "task_type": "rca", "latency_ms": 1500, "tokens_out": 64, "output": "root cause found"})
    assert len(store.get_recent_inferences()) == 1
    model_stats = store.get_model_summary()
    assert "deepseek" in model_stats
    assert model_stats["deepseek"]["total_calls"] == 1


def test_signal_store_tracks_cluster_stats():
    """Cluster stats: pod/node counts come from collector infra counts,
    update_cluster_stats only tracks warning events and namespace activity."""
    from types import SimpleNamespace
    store = SignalStore()
    signals = [
        SimpleNamespace(signal_type="event_backoff", namespace="stargate"),
        SimpleNamespace(signal_type="event_backoff", namespace="stargate"),
        SimpleNamespace(signal_type="pod_crashloop", namespace="deepfield"),
    ]
    store.update_cluster_stats("infra01", signals)
    clusters = store.get_cluster_summary()
    assert "infra01" in clusters
    assert clusters["infra01"]["total_events_warning"] == 2
    assert clusters["infra01"]["namespaces"]["stargate"] == 2
    assert clusters["infra01"]["namespaces"]["deepfield"] == 1


def test_signal_store_respects_max_size():
    store = SignalStore(max_signals=5)
    for i in range(10):
        store.add_signal({"signal_type": f"test_{i}", "namespace": "ns"})
    assert len(store.get_recent_signals()) == 5


def test_agent_stats_accumulate():
    store = SignalStore()
    for _ in range(3):
        store.add_decision({"filter_name": "DedupeAgent", "outcome": "dedupe"})
    for _ in range(2):
        store.add_decision({"filter_name": "DedupeAgent", "outcome": "keep"})
    stats = store.get_agent_summary()["DedupeAgent"]
    assert stats["deduped"] == 3
    assert stats["kept"] == 2
    assert stats["total_evaluated"] == 5
