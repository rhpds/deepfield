"""Tests for synthetic fleet generator."""

from app.generators.synthetic import SyntheticFleetGenerator
from app.generators.signal_types import FAILURE_SIGNALS


def test_synthetic_generator_is_deterministic_by_seed():
    gen1 = SyntheticFleetGenerator("tiny", seed=42)
    gen2 = SyntheticFleetGenerator("tiny", seed=42)
    clusters1, signals1 = gen1.generate()
    clusters2, signals2 = gen2.generate()
    assert len(signals1) == len(signals2)
    assert signals1[0].signal_id == signals2[0].signal_id
    assert signals1[-1].signal_type == signals2[-1].signal_type
    for i in range(min(50, len(signals1))):
        assert signals1[i].signal_id == signals2[i].signal_id
        assert signals1[i].signal_type == signals2[i].signal_type


def test_synthetic_different_seeds_produce_different_output():
    gen1 = SyntheticFleetGenerator("tiny", seed=42)
    gen2 = SyntheticFleetGenerator("tiny", seed=99)
    _, signals1 = gen1.generate()
    _, signals2 = gen2.generate()
    types1 = [s.signal_type for s in signals1]
    types2 = [s.signal_type for s in signals2]
    assert types1 != types2


def test_synthetic_tiny_profile_generates_expected_counts():
    gen = SyntheticFleetGenerator("tiny", seed=42)
    clusters, signals = gen.generate()
    assert len(clusters) == 1
    assert len(signals) == 1000


def test_synthetic_small_profile_generates_expected_counts():
    gen = SyntheticFleetGenerator("small", seed=42)
    clusters, signals = gen.generate()
    assert len(clusters) == 5
    assert len(signals) == 10_000


def test_synthetic_failure_scenarios_generate_failures():
    gen = SyntheticFleetGenerator("small", seed=42)
    _, signals = gen.generate()
    failure_types = set(FAILURE_SIGNALS)
    signal_types = {s.signal_type for s in signals}
    assert signal_types & failure_types, f"No failure signals found in {signal_types}"


def test_synthetic_signals_have_valid_fields():
    gen = SyntheticFleetGenerator("tiny", seed=42)
    clusters, signals = gen.generate()
    cluster_ids = {c.cluster_id for c in clusters}
    for sig in signals[:100]:
        assert sig.cluster_id in cluster_ids
        assert sig.namespace.startswith("ns-")
        assert sig.source == "synthetic"
        assert sig.resource_kind != ""
        assert sig.resource_name != ""


def test_synthetic_max_q_with_overrides():
    gen = SyntheticFleetGenerator("max_q", seed=42, clusters=3, total_events=500)
    clusters, signals = gen.generate()
    assert len(clusters) == 3
    assert len(signals) == 500
