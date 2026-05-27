"""Capacity projection calculator."""

from dataclasses import dataclass, asdict


@dataclass
class CapacityEstimate:
    reasoning_compression_ratio: float
    max_reasoning_tasks_per_minute: float
    max_raw_signals_per_minute: float
    avg_raw_signals_per_cluster_per_minute: float
    projected_clusters_supported: int
    p95_latency_ms: float
    assumptions: dict


def compute_capacity_projection(
    reasoning_compression_ratio: float,
    max_reasoning_tasks_per_minute: float,
    avg_raw_signals_per_cluster_per_minute: float,
    p95_latency_ms: float = 0,
) -> CapacityEstimate:
    max_raw = max_reasoning_tasks_per_minute * reasoning_compression_ratio
    projected = int(max_raw / avg_raw_signals_per_cluster_per_minute) if avg_raw_signals_per_cluster_per_minute > 0 else 0

    return CapacityEstimate(
        reasoning_compression_ratio=round(reasoning_compression_ratio, 1),
        max_reasoning_tasks_per_minute=round(max_reasoning_tasks_per_minute, 2),
        max_raw_signals_per_minute=round(max_raw, 0),
        avg_raw_signals_per_cluster_per_minute=round(avg_raw_signals_per_cluster_per_minute, 2),
        projected_clusters_supported=projected,
        p95_latency_ms=round(p95_latency_ms, 2),
        assumptions={
            "formula": "projected_clusters = (max_reasoning_tasks/min * compression_ratio) / avg_signals_per_cluster/min",
            "reasoning_compression_ratio": round(reasoning_compression_ratio, 1),
            "max_reasoning_tasks_per_minute": round(max_reasoning_tasks_per_minute, 2),
            "avg_raw_signals_per_cluster_per_minute": round(avg_raw_signals_per_cluster_per_minute, 2),
        },
    )
