"""Benchmark metrics aggregation and saturation detection."""

from dataclasses import dataclass


@dataclass
class BenchmarkMetrics:
    model_name: str
    hardware_lane: str
    concurrency_level: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    timeout_count: int
    tokens_in: int
    tokens_out: int
    tokens_per_second: float
    requests_per_second: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    error_rate: float
    stable: bool


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_v):
        return sorted_v[-1]
    return sorted_v[f] + (k - f) * (sorted_v[c] - sorted_v[f])


def aggregate_benchmark_results(
    results: list[dict],
    concurrency_level: int = 1,
    total_duration_ms: float = 0,
    p95_target_ms: float = 10000,
    error_rate_target: float = 0.05,
) -> list[BenchmarkMetrics]:
    by_model: dict[str, list[dict]] = {}
    for r in results:
        model = r["model_name"]
        by_model.setdefault(model, []).append(r)

    metrics_list = []
    for model, model_results in by_model.items():
        latencies = [r["latency_ms"] for r in model_results if r.get("status") == "success"]
        successes = [r for r in model_results if r.get("status") == "success"]
        failures = [r for r in model_results if r.get("status") != "success"]
        timeouts = [r for r in failures if r.get("error", "").startswith("timeout")]

        total_tokens_in = sum(r.get("tokens_in", 0) for r in successes)
        total_tokens_out = sum(r.get("tokens_out", 0) for r in successes)
        total_tps = sum(r.get("tokens_per_second", 0) for r in successes)
        avg_tps = total_tps / len(successes) if successes else 0

        duration_s = total_duration_ms / 1000 if total_duration_ms > 0 else max(1, sum(latencies) / 1000)
        rps = len(successes) / duration_s if duration_s > 0 else 0

        error_rate = len(failures) / len(model_results) if model_results else 0
        p95 = percentile(latencies, 95)
        stable = p95 <= p95_target_ms and error_rate <= error_rate_target

        hw = model_results[0].get("hardware_lane", "unknown") if model_results else "unknown"

        metrics_list.append(
            BenchmarkMetrics(
                model_name=model,
                hardware_lane=hw,
                concurrency_level=concurrency_level,
                total_requests=len(model_results),
                successful_requests=len(successes),
                failed_requests=len(failures),
                timeout_count=len(timeouts),
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                tokens_per_second=round(avg_tps, 2),
                requests_per_second=round(rps, 2),
                p50_latency_ms=round(percentile(latencies, 50), 2),
                p95_latency_ms=round(p95, 2),
                p99_latency_ms=round(percentile(latencies, 99), 2),
                min_latency_ms=round(min(latencies), 2) if latencies else 0,
                max_latency_ms=round(max(latencies), 2) if latencies else 0,
                error_rate=round(error_rate, 4),
                stable=stable,
            )
        )

    return metrics_list


def detect_saturation_point(
    metrics_by_concurrency: list[BenchmarkMetrics],
    p95_target_ms: float = 10000,
    error_rate_target: float = 0.05,
) -> dict:
    stable_levels = [m for m in metrics_by_concurrency if m.stable]
    unstable_levels = [m for m in metrics_by_concurrency if not m.stable]

    if not stable_levels:
        return {
            "saturated_at_concurrency": metrics_by_concurrency[0].concurrency_level if metrics_by_concurrency else 0,
            "max_stable_concurrency": 0,
            "max_stable_rps": 0,
            "max_stable_tps": 0,
        }

    max_stable = max(stable_levels, key=lambda m: m.concurrency_level)
    return {
        "saturated_at_concurrency": unstable_levels[0].concurrency_level if unstable_levels else None,
        "max_stable_concurrency": max_stable.concurrency_level,
        "max_stable_rps": max_stable.requests_per_second,
        "max_stable_tps": max_stable.tokens_per_second,
        "max_stable_p95_ms": max_stable.p95_latency_ms,
    }
