"""Benchmark workload profiles."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BenchmarkProfile:
    name: str
    description: str
    task_types: list[str]
    models: list[str]
    requests_per_model: int
    concurrency_levels: list[int] = field(default_factory=lambda: [1])
    max_output_tokens: int = 128
    duration_minutes: Optional[int] = None


ALL_MODELS = [
    "deepseek_r1_distill_qwen_14b_gaudi",
    "phi4_gaudi",
    "qwen3_14b_gaudi_a",
    "qwen3_14b_gaudi_b",
    "llama_3_1_70b_q4_xeon",
]

GAUDI_MODELS = [
    "deepseek_r1_distill_qwen_14b_gaudi",
    "phi4_gaudi",
    "qwen3_14b_gaudi_a",
    "qwen3_14b_gaudi_b",
]


PROFILES: dict[str, BenchmarkProfile] = {
    "endpoint_sanity": BenchmarkProfile(
        name="endpoint_sanity",
        description="Verify every endpoint responds",
        task_types=["fast_summary"],
        models=ALL_MODELS,
        requests_per_model=3,
        concurrency_levels=[1],
        max_output_tokens=32,
    ),
    "model_race": BenchmarkProfile(
        name="model_race",
        description="Same prompts across all models — compare latency, tokens/sec",
        task_types=["general_summary", "root_cause_analysis", "structured_json_output"],
        models=ALL_MODELS,
        requests_per_model=10,
        concurrency_levels=[1, 8],
        max_output_tokens=256,
    ),
    "gaudi_race": BenchmarkProfile(
        name="gaudi_race",
        description="Gaudi-only model race — no CPU bottleneck",
        task_types=["general_summary", "root_cause_analysis", "structured_json_output"],
        models=GAUDI_MODELS,
        requests_per_model=15,
        concurrency_levels=[1, 8, 25],
        max_output_tokens=256,
    ),
    "gaudi_blast": BenchmarkProfile(
        name="gaudi_blast",
        description="Max throughput — all Gaudi models, high concurrency per model",
        task_types=["fast_summary"],
        models=GAUDI_MODELS,
        requests_per_model=50,
        concurrency_levels=[25, 50],
        max_output_tokens=64,
    ),
    "max_throughput": BenchmarkProfile(
        name="max_throughput",
        description="Absolute max — short requests, extreme concurrency, find the wall",
        task_types=["fast_summary"],
        models=GAUDI_MODELS,
        requests_per_model=100,
        concurrency_levels=[50, 100],
        max_output_tokens=32,
    ),
    "full_fleet": BenchmarkProfile(
        name="full_fleet",
        description="All hardware — Gaudi 3 + Xeon 6 in parallel",
        task_types=["general_summary", "root_cause_analysis", "fast_summary"],
        models=ALL_MODELS,
        requests_per_model=20,
        concurrency_levels=[10, 25],
        max_output_tokens=128,
    ),
    "token_cannon": BenchmarkProfile(
        name="token_cannon",
        description="Output-heavy generation — measure max tokens/sec",
        task_types=["token_generation"],
        models=GAUDI_MODELS,
        requests_per_model=20,
        concurrency_levels=[4, 8, 16],
        max_output_tokens=2048,
    ),
    "reasoning_gauntlet": BenchmarkProfile(
        name="reasoning_gauntlet",
        description="RCA, troubleshooting, multi-step reasoning — Gaudi only",
        task_types=["root_cause_analysis", "cross_cluster_correlation", "fleet_summary"],
        models=["deepseek_r1_distill_qwen_14b_gaudi", "qwen3_14b_gaudi_a"],
        requests_per_model=15,
        concurrency_levels=[1, 4, 8],
        max_output_tokens=512,
    ),
    "fleet_summary": BenchmarkProfile(
        name="fleet_summary",
        description="Synthetic cluster findings summarized into fleet reports",
        task_types=["fleet_summary", "general_summary"],
        models=["qwen3_14b_gaudi_a", "phi4_gaudi", "llama_3_1_70b_q4_xeon"],
        requests_per_model=10,
        concurrency_levels=[1, 2],
        max_output_tokens=512,
    ),
    "sustained_overdrive": BenchmarkProfile(
        name="sustained_overdrive",
        description="30-60 minute mixed workload, ramps concurrency",
        task_types=["general_summary", "root_cause_analysis", "fast_summary", "token_generation"],
        models=ALL_MODELS,
        requests_per_model=100,
        concurrency_levels=[1, 2, 4, 8, 16],
        max_output_tokens=256,
        duration_minutes=30,
    ),
    "saturation_curve": BenchmarkProfile(
        name="saturation_curve",
        description="Ramp concurrency to find saturation point per model",
        task_types=["general_summary"],
        models=ALL_MODELS,
        requests_per_model=20,
        concurrency_levels=[1, 2, 4, 8, 16, 32, 64, 128],
        max_output_tokens=128,
    ),
}

TASK_PROMPTS: dict[str, list[str]] = {
    "fast_summary": [
        "Summarize the current cluster health status in one paragraph.",
        "Give a brief overview of namespace resource utilization.",
        "Summarize the pod restart events from the last hour.",
    ],
    "general_summary": [
        "Provide a detailed summary of the cluster state including node health, pod status, and resource utilization across all namespaces.",
        "Analyze the current fleet state and identify the top 3 areas of concern.",
        "Generate a fleet health report covering all monitored clusters.",
    ],
    "root_cause_analysis": [
        "Multiple pods in namespace ns-prod-0042 are in CrashLoopBackOff. The deployment was updated 15 minutes ago. Node worker-07 shows memory pressure. Analyze the root cause.",
        "The inference endpoint for deepseek-r1 has been returning 503 errors for the last 5 minutes. KV cache utilization is at 95%. Queue depth is 47. Diagnose the issue.",
        "Cross-cluster correlation shows model latency spikes on 3 clusters simultaneously. All clusters share the same Gaudi inference backend. Determine root cause.",
    ],
    "cross_cluster_correlation": [
        "Correlate the following signals across 5 clusters: node pressure on 2 clusters, pod evictions on 3 clusters, PVC pending on 1 cluster. What is the common thread?",
        "Three clusters report kserve_not_ready for different models at the same timestamp. Is this a shared infrastructure issue?",
    ],
    "fleet_summary": [
        "Generate a fleet-wide summary for 25 clusters covering the last hour. Include: total signals processed, findings by severity, top 5 affected namespaces, and recommended actions.",
        "Produce a capacity planning report for the inference cluster based on current utilization and projected growth.",
    ],
    "structured_json_output": [
        'Analyze this finding and return a JSON object with keys: severity, affected_resources, root_cause, recommended_action, confidence_score.',
        'Extract structured data from this cluster event: node worker-03 DiskPressure True, 5 pods evicted, PVC data-worker-03 stuck Pending.',
    ],
    "token_generation": [
        "Write a detailed incident report for a production outage affecting the inference platform. Include timeline, impact assessment, root cause analysis, and remediation steps.",
        "Generate a comprehensive architecture review document for an OpenShift AI inference platform running on Intel Gaudi 3 hardware.",
    ],
    "critic_or_baseline": [
        "Review the following RCA output and identify any logical gaps or unsupported conclusions.",
        "Evaluate whether this fleet summary accurately represents the cluster state based on the provided signals.",
    ],
}


def get_profile(name: str) -> BenchmarkProfile:
    if name not in PROFILES:
        raise ValueError(f"Unknown benchmark profile: {name}. Available: {list(PROFILES.keys())}")
    return PROFILES[name]
