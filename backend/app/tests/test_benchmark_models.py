"""Tests for benchmark domain models."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.models import BenchmarkRequest, BenchmarkRun


def test_benchmark_request_model_accepts_valid_request():
    req = BenchmarkRequest(
        benchmark_run_id=uuid4(),
        workload_profile="model_race",
        task_type="root_cause_analysis",
        prompt="Analyze the pod crashloop in namespace prod-042.",
        input_tokens_estimate=40,
        expected_output_tokens=256,
        model_preference="deepseek_r1_distill_qwen_14b_gaudi",
    )
    assert req.request_id is not None
    assert req.workload_profile == "model_race"
    assert req.input_tokens_estimate == 40


def test_benchmark_run_model_accepts_model_race():
    run = BenchmarkRun(
        profile="model_race",
        model_profiles=["deepseek_r1_distill_qwen_14b_gaudi", "phi4_gaudi", "qwen3_14b_gaudi_a"],
        concurrency_levels=[1, 2, 4, 8],
        request_count=100,
    )
    assert run.status == "pending"
    assert run.profile == "model_race"
    assert len(run.model_profiles) == 3
    assert run.benchmark_run_id is not None
