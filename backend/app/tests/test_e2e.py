"""End-to-end integration tests."""

from app.orchestrator import run_synthetic, run_benchmark, run_capacity_projection


def test_e2e_synthetic_tiny_completes():
    result = run_synthetic(profile="tiny", seed=42)

    assert result["mode"] == "synthetic"
    assert result["profile"] == "tiny"
    assert result["raw_signals"] == 1000
    assert result["clusters"] == 1
    assert result["normalized"] == 1000
    assert result["findings"] >= 0
    assert result["reasoning_tasks"] >= 0
    assert result["duration_ms"] > 0

    funnel = result["funnel"]
    assert funnel["raw_signals_received"] == 1000
    assert funnel["reasoning_compression_ratio"] > 0
    assert funnel["signal_reduction_percent"] >= 0

    assert "DeepField Run Report" in result["report_md"]
    assert result["report_json"] is not None


def test_e2e_benchmark_model_race_completes():
    result = run_benchmark(profile="model_race", seed=42, mode="mock")

    assert result["mode"] == "mock"
    assert result["total_requests"] > 0
    assert result["benchmark_run_id"] is not None
    assert len(result["model_metrics"]) > 1
    assert "saturation" in result
    assert "DeepField Benchmark Report" in result["report_md"]

    for model, metrics in result["model_metrics"].items():
        assert metrics["total_requests"] > 0
        assert metrics["tokens_per_second"] > 0


def test_e2e_synthetic_plus_benchmark_capacity_projection_completes():
    synthetic = run_synthetic(profile="small", seed=42)
    benchmark = run_benchmark(profile="model_race", seed=42, mode="mock")

    projection = run_capacity_projection(synthetic, benchmark)

    assert projection["compression_ratio"] > 0
    assert projection["projected_clusters_supported"] > 0
    assert projection["max_reasoning_tasks_per_minute"] > 0
    assert projection["avg_signals_per_cluster"] > 0

    print(f"\n--- CAPACITY PROJECTION ---")
    print(f"Compression Ratio: {projection['compression_ratio']:,.1f}:1")
    print(f"Projected Clusters: {projection['projected_clusters_supported']}")
    print(f"Max Reasoning/min: {projection['max_reasoning_tasks_per_minute']:,.1f}")
