"""Tests for report generators."""

import json

from app.metrics.funnel import SignalFunnel
from app.metrics.capacity import CapacityEstimate
from app.benchmark.metrics import BenchmarkMetrics
from app.reports.run_report import generate_run_report_json, generate_run_report_md
from app.reports.benchmark_report import (
    generate_benchmark_report_json,
    generate_benchmark_report_md,
    generate_saturation_csv,
)


def _funnel():
    return SignalFunnel(
        raw_signals_received=10000,
        normalized_signals=10000,
        dropped_signals=9400,
        deduped_signals=200,
        suppressed_transients=100,
        retained_signals=600,
        correlated_findings=50,
        reasoning_tasks_created=5,
        final_insights_created=3,
        signal_reduction_percent=94.0,
        llm_escalation_rate_percent=0.05,
        reasoning_compression_ratio=2000.0,
    )


def _capacity():
    return CapacityEstimate(
        reasoning_compression_ratio=2000.0,
        max_reasoning_tasks_per_minute=30.0,
        max_raw_signals_per_minute=60000.0,
        avg_raw_signals_per_cluster_per_minute=500.0,
        projected_clusters_supported=120,
        p95_latency_ms=850.0,
        assumptions={"formula": "test"},
    )


def _metrics():
    return [
        BenchmarkMetrics(
            model_name="phi4_gaudi", hardware_lane="gaudi3", concurrency_level=1,
            total_requests=50, successful_requests=50, failed_requests=0, timeout_count=0,
            tokens_in=5000, tokens_out=3200, tokens_per_second=85.0, requests_per_second=12.5,
            p50_latency_ms=350, p95_latency_ms=500, p99_latency_ms=650,
            min_latency_ms=200, max_latency_ms=700, error_rate=0.0, stable=True,
        ),
        BenchmarkMetrics(
            model_name="deepseek_r1_distill_qwen_14b_gaudi", hardware_lane="gaudi3", concurrency_level=1,
            total_requests=50, successful_requests=48, failed_requests=2, timeout_count=0,
            tokens_in=5000, tokens_out=4000, tokens_per_second=60.0, requests_per_second=8.0,
            p50_latency_ms=800, p95_latency_ms=1200, p99_latency_ms=1500,
            min_latency_ms=500, max_latency_ms=1600, error_rate=0.04, stable=True,
        ),
    ]


def test_report_writer_outputs_deepfield_run_report():
    report_json = generate_run_report_json("run-001", "synthetic", "tiny", _funnel(), _capacity())
    parsed = json.loads(report_json)
    assert parsed["run_id"] == "run-001"
    assert parsed["signal_funnel"]["reasoning_compression_ratio"] == 2000.0
    assert parsed["capacity_projection"]["projected_clusters_supported"] == 120

    report_md = generate_run_report_md("run-001", "synthetic", "tiny", _funnel(), _capacity())
    assert "Reasoning Compression Ratio: 2,000.0:1" in report_md
    assert "Projected clusters supported: 120" in report_md


def test_report_writer_outputs_capacity_projection():
    report_md = generate_run_report_md("run-001", "synthetic", "tiny", _funnel(), _capacity())
    assert "Capacity Projection" in report_md
    assert "120" in report_md


def test_report_writer_outputs_benchmark_run_report():
    metrics = _metrics()
    saturation = {"phi4_gaudi": {"max_stable_concurrency": 16, "max_stable_rps": 12.5}}

    report_json = generate_benchmark_report_json("bench-001", "model_race", metrics, saturation)
    parsed = json.loads(report_json)
    assert parsed["profile"] == "model_race"
    assert len(parsed["model_metrics"]) == 2

    report_md = generate_benchmark_report_md("bench-001", "model_race", metrics, saturation)
    assert "phi4_gaudi" in report_md
    assert "deepseek" in report_md
    assert "Saturation Points" in report_md


def test_report_writer_outputs_saturation_curve_csv():
    metrics = [
        BenchmarkMetrics(
            model_name="phi4_gaudi", hardware_lane="gaudi3", concurrency_level=c,
            total_requests=20, successful_requests=20, failed_requests=0, timeout_count=0,
            tokens_in=2000, tokens_out=1200, tokens_per_second=85.0, requests_per_second=10.0+c,
            p50_latency_ms=300+c*10, p95_latency_ms=500+c*20, p99_latency_ms=600+c*30,
            min_latency_ms=200, max_latency_ms=700+c*50, error_rate=0.0, stable=c<=32,
        )
        for c in [1, 2, 4, 8, 16, 32, 64]
    ]
    csv_output = generate_saturation_csv(metrics)
    lines = csv_output.strip().split("\n")
    assert lines[0].startswith("model_name")
    assert len(lines) == 8  # header + 7 data rows
    assert "phi4_gaudi" in lines[1]
