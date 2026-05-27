"""Tests for three-tier inference routing (nano → micro → macro)."""

from uuid import uuid4

from app.domain.models import ReasoningTask
from app.inference.router import resolve_model, resolve_tier, MACRO_MODELS, MICRO_MODELS


def _task(task_type, preference="auto"):
    return ReasoningTask(
        finding_id=uuid4(),
        task_type=task_type,
        model_preference=preference,
        prompt="Test prompt",
    )


def test_model_router_selects_macro_for_reasoning():
    model = resolve_model(_task("root_cause_analysis"))
    assert model in MACRO_MODELS


def test_model_router_selects_micro_for_fast_summary():
    model = resolve_model(_task("summarize_finding"))
    assert model in MICRO_MODELS


def test_model_router_selects_macro_for_fleet_summary():
    model = resolve_model(_task("fleet_summary"))
    assert model in MACRO_MODELS


def test_model_router_selects_llama_for_cpu_baseline():
    model = resolve_model(_task("root_cause_analysis", preference="llama70b"))
    assert model == "llama_3_1_70b_q4_xeon"


def test_preference_overrides_auto_routing():
    model = resolve_model(_task("summarize_finding", preference="deepseek"))
    assert model == "deepseek_r1_distill_qwen_14b_gaudi"


def test_micro_preference_routes_to_xeon():
    model = resolve_model(_task("summarize_finding", preference="granite_2b_cpu"))
    assert model == "granite_2b_cpu_xeon"


def test_tier_classification():
    assert resolve_tier(_task("summarize_finding")) == "micro"
    assert resolve_tier(_task("root_cause_analysis")) == "macro"
    assert resolve_tier(_task("cross_cluster_correlation")) == "macro"
    assert resolve_tier(_task("fleet_summary")) == "macro"
