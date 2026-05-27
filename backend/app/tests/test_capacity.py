"""Tests for capacity projection."""

from uuid import uuid4

from app.domain.models import FilterDecision, NormalizedSignal, CandidateFinding, ReasoningTask
from app.metrics.funnel import compute_funnel
from app.metrics.capacity import compute_capacity_projection
from datetime import datetime, timezone


def test_capacity_projection_computes_reasoning_compression_ratio():
    raw_count = 10000
    normalized = [
        NormalizedSignal(
            signal_id=uuid4(), cluster_id=uuid4(), namespace="ns", resource_kind="Pod",
            resource_name="p", signal_type="pod_running", severity="info",
            confidence=0.99, timestamp=datetime.now(timezone.utc),
        )
        for _ in range(raw_count)
    ]
    tasks = [
        ReasoningTask(finding_id=uuid4(), task_type="summarize_finding", prompt="x")
        for _ in range(5)
    ]
    funnel = compute_funnel(raw_count, normalized, [], [], tasks)
    assert funnel.reasoning_compression_ratio == 2000.0
    assert funnel.reasoning_tasks_created == 5


def test_capacity_projection_computes_projected_clusters_supported():
    estimate = compute_capacity_projection(
        reasoning_compression_ratio=2000.0,
        max_reasoning_tasks_per_minute=30.0,
        avg_raw_signals_per_cluster_per_minute=500.0,
    )
    # 30 * 2000 = 60000 raw signals/min / 500 per cluster = 120 clusters
    assert estimate.projected_clusters_supported == 120
    assert estimate.max_raw_signals_per_minute == 60000


def test_capacity_projection_uses_benchmark_max_reasoning_throughput():
    estimate = compute_capacity_projection(
        reasoning_compression_ratio=5000.0,
        max_reasoning_tasks_per_minute=60.0,
        avg_raw_signals_per_cluster_per_minute=1000.0,
        p95_latency_ms=850.0,
    )
    # 60 * 5000 = 300000 / 1000 = 300 clusters
    assert estimate.projected_clusters_supported == 300
    assert estimate.p95_latency_ms == 850.0
    assert "formula" in estimate.assumptions
