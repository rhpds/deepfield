"""End-to-end DeepField pipeline orchestrator."""

import time
from dataclasses import asdict
from typing import Optional
from uuid import uuid4

from app.collectors.synthetic import SyntheticCollector
from app.normalizers.signal_normalizer import normalize_batch
from app.nanoagents.pipeline import run_pipeline
from app.correlation.engine import correlate
from app.routing.signal_router import route_signals, create_reasoning_tasks
from app.inference.client import InferenceClient, MockInferenceClient
from app.inference.router import resolve_model, resolve_route
from app.metrics.funnel import compute_funnel
from app.metrics.capacity import compute_capacity_projection
from app.benchmark.runner import BenchmarkRunner
from app.reports.run_report import generate_run_report_json, generate_run_report_md
from app.reports.benchmark_report import generate_benchmark_report_json, generate_benchmark_report_md


def run_synthetic(
    profile: str = "tiny",
    seed: int = 42,
    inference_client: Optional[InferenceClient] = None,
    **overrides,
) -> dict:
    from datetime import datetime, timezone
    client = inference_client or MockInferenceClient(seed=seed)
    run_id = str(uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()

    collector = SyntheticCollector(profile=profile, seed=seed, **overrides)
    clusters, raw_signals = collector.collect()

    normalized = normalize_batch(raw_signals)

    pipeline_result = run_pipeline(normalized)
    decisions = pipeline_result["decisions"]
    remaining = pipeline_result["remaining_signals"]

    routing_result = route_signals(normalized, decisions)
    kept_signals = routing_result["kept"]

    findings = correlate(kept_signals)

    tasks = create_reasoning_tasks(findings)

    inference_results = []
    for task in tasks:
        model = resolve_model(task)
        route = resolve_route(task)
        resp = client.infer(model=model, prompt=task.prompt, max_tokens=256)
        inference_results.append({
            "task_id": str(task.task_id),
            "model": model,
            "route": route,
            "status": resp.status,
            "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out,
            "latency_ms": resp.latency_ms,
        })

    duration_ms = (time.monotonic() - start) * 1000

    funnel = compute_funnel(
        raw_count=len(raw_signals),
        normalized=normalized,
        decisions=decisions,
        findings=findings,
        tasks=tasks,
        insights_count=len(inference_results),
    )

    signals_per_cluster_per_min = len(raw_signals) / max(len(clusters), 1)

    report_json = generate_run_report_json(run_id, "synthetic", profile, funnel, duration_ms=duration_ms)
    report_md = generate_run_report_md(run_id, "synthetic", profile, funnel, duration_ms=duration_ms)

    return {
        "run_id": run_id,
        "mode": "synthetic",
        "profile": profile,
        "seed": seed,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration_ms, 2),
        "clusters": len(clusters),
        "raw_signals": len(raw_signals),
        "normalized": len(normalized),
        "pipeline": {
            "suppressed": pipeline_result["suppressed_count"],
            "deduped": pipeline_result["deduped_count"],
            "escalated": len(pipeline_result["escalated"]),
            "remaining": pipeline_result["retained_count"],
        },
        "routing": {
            "kept": routing_result["kept_count"],
            "dropped": routing_result["dropped_count"],
        },
        "findings": len(findings),
        "reasoning_tasks": len(tasks),
        "inference_results": inference_results,
        "funnel": asdict(funnel),
        "avg_signals_per_cluster": signals_per_cluster_per_min,
        "report_json": report_json,
        "report_md": report_md,
    }


def run_benchmark(
    profile: str = "model_race",
    seed: int = 42,
    mode: str = "mock",
    inference_client: Optional[InferenceClient] = None,
) -> dict:
    client = inference_client or MockInferenceClient(seed=seed)
    runner = BenchmarkRunner(client, seed=seed)
    result = runner.run(profile)

    from app.benchmark.metrics import BenchmarkMetrics
    metrics = []
    for model, m_dict in result.get("model_metrics", {}).items():
        metrics.append(BenchmarkMetrics(**m_dict))

    report_json = generate_benchmark_report_json(
        result["benchmark_run_id"], profile, metrics, result.get("saturation", {}),
        duration_ms=result.get("duration_ms", 0),
    )
    report_md = generate_benchmark_report_md(
        result["benchmark_run_id"], profile, metrics, result.get("saturation", {}),
    )

    result["report_json"] = report_json
    result["report_md"] = report_md
    result["mode"] = mode
    return result


def run_capacity_projection(
    synthetic_result: dict,
    benchmark_result: dict,
) -> dict:
    funnel = synthetic_result["funnel"]
    compression_ratio = funnel["reasoning_compression_ratio"]
    avg_signals_per_cluster = synthetic_result["avg_signals_per_cluster"]

    # Sum RPS across all models — they run in parallel
    total_rps = 0
    worst_p95 = 0
    model_breakdown = {}

    for model, m_dict in benchmark_result.get("model_metrics", {}).items():
        rps = m_dict.get("requests_per_second", 0)
        p95 = m_dict.get("p95_latency_ms", 0)
        total_rps += rps
        worst_p95 = max(worst_p95, p95)
        model_breakdown[model] = {
            "rps": round(rps, 2),
            "p95_ms": round(p95, 1),
            "hardware": m_dict.get("hardware_lane", "unknown"),
            "tok_s": m_dict.get("tokens_per_second", 0),
        }

    max_rps = total_rps
    max_p95 = worst_p95

    max_reasoning_per_min = max_rps * 60

    projection = compute_capacity_projection(
        reasoning_compression_ratio=compression_ratio,
        max_reasoning_tasks_per_minute=max_reasoning_per_min,
        avg_raw_signals_per_cluster_per_minute=avg_signals_per_cluster,
        p95_latency_ms=max_p95,
    )

    return {
        "projection": asdict(projection),
        "compression_ratio": compression_ratio,
        "max_reasoning_tasks_per_minute": max_reasoning_per_min,
        "total_rps_all_models": round(total_rps, 2),
        "avg_signals_per_cluster": avg_signals_per_cluster,
        "projected_clusters_supported": projection.projected_clusters_supported,
        "p95_latency_ms": max_p95,
        "model_breakdown": model_breakdown,
        "benchmark_mode": benchmark_result.get("mode", "mock"),
    }
