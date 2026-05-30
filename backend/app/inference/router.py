"""Three-tier inference routing: nano (deterministic) → micro (Xeon 6) → macro (Gaudi 3)."""

from typing import List

from app.domain.models import ReasoningTask

# === Macro agents — Gaudi 3 GPU, deep reasoning (50-60 tok/s) ===
MACRO_MODELS = [
    "deepseek_r1_distill_qwen_14b_gaudi",
    "phi4_gaudi",
    "qwen3_14b_gaudi_a",
    "qwen3_14b_gaudi_b",
]

# === Micro agents — Xeon 6 CPU, fast triage (15-28 tok/s via OpenVINO) ===
MICRO_MODELS = [
    "granite_2b_cpu_xeon",
    "phi3_mini_cpu_xeon",
    "qwen25_3b_cpu_xeon",
]

# Task type → tier
TASK_TO_TIER = {
    "summarize_finding": "micro",
    "root_cause_analysis": "macro",
    "cross_cluster_correlation": "macro",
    "fleet_summary": "macro",
    "capacity_estimate": "macro",
    # Micro-tier task types (Xeon 6 CPU — fast, low-token)
    "classify_signal": "micro",
    "correlate_findings": "micro",
    "suggest_remediation": "micro",
    "explain_signal": "micro",
    "filter_noise": "micro",
}

# Model preference → actual endpoint
PREFERENCE_TO_MODEL = {
    # Macro (Gaudi 3)
    "phi4": "phi4_gaudi",
    "qwen3": "qwen3_14b_gaudi_a",
    "qwen3b": "qwen3_14b_gaudi_b",
    "deepseek": "deepseek_r1_distill_qwen_14b_gaudi",
    # Micro (Xeon 6)
    "granite_2b_cpu": "granite_2b_cpu_xeon",
    "phi3_mini_cpu": "phi3_mini_cpu_xeon",
    "qwen25_3b_cpu": "qwen25_3b_cpu_xeon",
    # Legacy
    "llama70b": "llama_3_1_70b_q4_xeon",
}

_macro_idx = 0
_micro_idx = 0


def resolve_model(task: ReasoningTask) -> str:
    global _macro_idx, _micro_idx

    # Explicit preference takes priority
    if task.model_preference != "auto" and task.model_preference in PREFERENCE_TO_MODEL:
        return PREFERENCE_TO_MODEL[task.model_preference]

    # Route by tier
    tier = TASK_TO_TIER.get(task.task_type, "micro")

    if tier == "macro":
        model = MACRO_MODELS[_macro_idx % len(MACRO_MODELS)]
        _macro_idx += 1
        return model
    else:
        model = MICRO_MODELS[_micro_idx % len(MICRO_MODELS)]
        _micro_idx += 1
        return model


def resolve_route(task: ReasoningTask) -> str:
    tier = TASK_TO_TIER.get(task.task_type, "micro")
    return f"{tier}:{task.task_type}"


def resolve_tier(task: ReasoningTask) -> str:
    return TASK_TO_TIER.get(task.task_type, "micro")
