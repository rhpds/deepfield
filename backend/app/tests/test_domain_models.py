"""Tests for DeepField domain models."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.models import (
    BenchmarkRequest,
    BenchmarkResult,
    BenchmarkRun,
    CandidateFinding,
    CapacityProjection,
    ClusterRef,
    DeepFieldRun,
    FilterDecision,
    FinalInsight,
    InferenceResult,
    NormalizedSignal,
    RawSignal,
    ReasoningTask,
)


def test_raw_signal_model_accepts_valid_signal():
    sig = RawSignal(
        cluster_id=uuid4(),
        namespace="ns-prod-001",
        resource_kind="Pod",
        resource_name="api-gateway-abc12",
        source="synthetic",
        signal_type="pod_crashloop",
        raw_payload={"restartCount": 5},
        timestamp=datetime.now(timezone.utc),
    )
    assert sig.signal_type == "pod_crashloop"
    assert sig.signal_id is not None


def test_normalized_signal_rejects_missing_cluster_id():
    with pytest.raises(ValidationError):
        NormalizedSignal(
            signal_id=uuid4(),
            namespace="ns-prod-001",
            resource_kind="Pod",
            resource_name="api-abc",
            signal_type="pod_crashloop",
            severity="high",
            confidence=0.95,
            timestamp=datetime.now(timezone.utc),
        )


def test_normalized_signal_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        NormalizedSignal(
            signal_id=uuid4(),
            cluster_id=uuid4(),
            namespace="ns-prod-001",
            resource_kind="Pod",
            resource_name="api-abc",
            signal_type="pod_crashloop",
            severity="banana",
            confidence=0.95,
            timestamp=datetime.now(timezone.utc),
        )


def test_cluster_ref_defaults():
    c = ClusterRef(display_name="test-cluster", environment="synthetic", source_type="synthetic")
    assert c.status == "active"
    assert c.cluster_id is not None
    assert c.metadata == {}


def test_filter_decision_outcome_literal():
    fd = FilterDecision(signal_id=uuid4(), filter_name="PodHealthAgent", outcome="drop", reason_code="info_noise")
    assert fd.outcome == "drop"
    with pytest.raises(ValidationError):
        FilterDecision(signal_id=uuid4(), filter_name="test", outcome="invalid_outcome", reason_code="x")


def test_reasoning_task_model_preference():
    rt = ReasoningTask(
        finding_id=uuid4(),
        task_type="root_cause_analysis",
        prompt="Analyze this failure",
        model_preference="deepseek",
    )
    assert rt.model_preference == "deepseek"
    assert rt.status == "pending"


def test_benchmark_run_accepts_valid():
    br = BenchmarkRun(
        profile="model_race",
        model_profiles=["deepseek", "phi4", "qwen3"],
        concurrency_levels=[1, 2, 4, 8],
        request_count=100,
    )
    assert br.status == "pending"
    assert len(br.concurrency_levels) == 4


def test_capacity_projection():
    cp = CapacityProjection(
        run_id=uuid4(),
        clusters_monitored=25,
        raw_signals_per_second=5000.0,
        reasoning_tasks_per_second=2.5,
        reasoning_compression_ratio=2000.0,
        p95_latency_ms=850.0,
        cpu_usage=45.0,
        memory_usage=62.0,
        projected_clusters_supported=150,
    )
    assert cp.projected_clusters_supported == 150
    assert cp.hpu_usage is None


def test_deepfield_run_defaults():
    run = DeepFieldRun(mode="synthetic", profile="tiny")
    assert run.status == "running"
    assert run.completed_at is None
    assert run.run_id is not None
