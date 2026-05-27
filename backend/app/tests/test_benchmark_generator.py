"""Tests for benchmark workload generator."""

from app.benchmark.generator import BenchmarkWorkloadGenerator
from app.benchmark.profiles import PROFILES


def test_benchmark_generator_is_deterministic_by_seed():
    gen1 = BenchmarkWorkloadGenerator("model_race", seed=42)
    gen2 = BenchmarkWorkloadGenerator("model_race", seed=42)
    reqs1 = gen1.generate()
    reqs2 = gen2.generate()
    assert len(reqs1) == len(reqs2)
    for r1, r2 in zip(reqs1, reqs2):
        assert r1.request_id == r2.request_id
        assert r1.prompt == r2.prompt
        assert r1.model_preference == r2.model_preference


def test_endpoint_sanity_profile_generates_expected_requests():
    gen = BenchmarkWorkloadGenerator("endpoint_sanity", seed=42)
    reqs = gen.generate()
    profile = PROFILES["endpoint_sanity"]
    expected = len(profile.models) * profile.requests_per_model
    assert len(reqs) == expected
    models_used = {r.model_preference for r in reqs}
    assert models_used == set(profile.models)


def test_model_race_profile_generates_same_prompts_for_all_models():
    gen = BenchmarkWorkloadGenerator("model_race", seed=42)
    reqs = gen.generate()
    by_model = {}
    for r in reqs:
        by_model.setdefault(r.model_preference, []).append(r)
    model_counts = [len(v) for v in by_model.values()]
    assert len(set(model_counts)) == 1, f"All models should get same count: {model_counts}"


def test_token_cannon_profile_generates_output_heavy_requests():
    gen = BenchmarkWorkloadGenerator("token_cannon", seed=42)
    reqs = gen.generate()
    for r in reqs:
        assert r.expected_output_tokens == 2048
        assert r.task_type == "token_generation"


def test_reasoning_gauntlet_profile_generates_reasoning_tasks():
    gen = BenchmarkWorkloadGenerator("reasoning_gauntlet", seed=42)
    reqs = gen.generate()
    reasoning_types = {"root_cause_analysis", "cross_cluster_correlation", "fleet_summary"}
    task_types = {r.task_type for r in reqs}
    assert task_types <= reasoning_types, f"Expected only reasoning tasks, got {task_types}"


def test_saturation_curve_profile_generates_concurrency_steps():
    profile = PROFILES["saturation_curve"]
    assert profile.concurrency_levels == [1, 2, 4, 8, 16, 32, 64, 128]
    gen = BenchmarkWorkloadGenerator("saturation_curve", seed=42)
    reqs = gen.generate()
    assert len(reqs) == len(profile.models) * profile.requests_per_model
