"""Pattern analyzer — generates tuning proposals from accumulated signal data.

Runs periodically (hourly) and produces proposals for:
- Noise resolution (noisy namespaces)
- Dedup window adjustments
- Model health issues
- New suppression rules
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4

logger = logging.getLogger("deepfield.analyzer")

NOISE_THRESHOLD = 0.90
DEDUP_THRESHOLD = 0.80
MODEL_ERROR_THRESHOLD = 0.15
MIN_SIGNALS_FOR_PROPOSAL = 100


def detect_noisy_namespaces(signal_counts: Dict[str, int], suppressed_counts: Dict[str, int],
                            cluster_id: str) -> List[dict]:
    """Detect namespaces where >90% of signals are suppressed/deduped."""
    proposals = []
    for ns, total in signal_counts.items():
        if total < MIN_SIGNALS_FOR_PROPOSAL:
            continue
        suppressed = suppressed_counts.get(ns, 0)
        noise_ratio = suppressed / total
        if noise_ratio >= NOISE_THRESHOLD:
            proposals.append({
                "proposal_id": f"noise-{cluster_id}-{ns}-{uuid4().hex[:8]}",
                "cluster_id": cluster_id,
                "category": "noise_resolution",
                "current_value": {"namespace": ns, "noise_ratio": round(noise_ratio, 3)},
                "proposed_value": {"action": "dampen", "threshold": 3, "window_seconds": 1800},
                "evidence": {
                    "namespace": ns,
                    "total_signals": total,
                    "suppressed": suppressed,
                    "noise_ratio": round(noise_ratio, 3),
                },
                "impact_estimate": f"Would suppress ~{int(noise_ratio * 100)}% of signals from {ns}",
                "confidence": min(0.95, noise_ratio),
            })
    return proposals


def detect_dedup_adjustments(type_counts: Dict[str, int], type_deduped: Dict[str, int],
                             cluster_id: str) -> List[dict]:
    """Detect signal types that need wider dedup windows."""
    proposals = []
    for sig_type, total in type_counts.items():
        if total < MIN_SIGNALS_FOR_PROPOSAL:
            continue
        deduped = type_deduped.get(sig_type, 0)
        dedup_ratio = deduped / total
        if dedup_ratio >= DEDUP_THRESHOLD:
            proposals.append({
                "proposal_id": f"dedup-{cluster_id}-{sig_type}-{uuid4().hex[:8]}",
                "cluster_id": cluster_id,
                "category": "threshold_adjustment",
                "current_value": {"signal_type": sig_type, "dedup_ratio": round(dedup_ratio, 3)},
                "proposed_value": {"dedup_window_seconds": 1800},
                "evidence": {
                    "signal_type": sig_type,
                    "total": total,
                    "deduped": deduped,
                    "dedup_ratio": round(dedup_ratio, 3),
                },
                "impact_estimate": f"Would reduce {sig_type} signals by ~{int(dedup_ratio * 100)}%",
                "confidence": min(0.9, dedup_ratio),
            })
    return proposals


def detect_model_issues(model_stats: Dict[str, dict], cluster_id: str) -> List[dict]:
    """Detect models with high error rates or excessive latency."""
    proposals = []
    for model, stats in model_stats.items():
        calls = stats.get("calls", 0)
        if calls < 50:
            continue
        error_rate = stats.get("error_rate", 0)
        avg_latency = stats.get("avg_latency", 0)

        if error_rate >= MODEL_ERROR_THRESHOLD:
            proposals.append({
                "proposal_id": f"model-{cluster_id}-{model}-{uuid4().hex[:8]}",
                "cluster_id": cluster_id,
                "category": "model_rotation",
                "current_value": {"model": model, "error_rate": round(error_rate, 3)},
                "proposed_value": {"action": "deprioritize"},
                "evidence": {
                    "model": model,
                    "calls": calls,
                    "errors": stats.get("errors", 0),
                    "error_rate": round(error_rate, 3),
                    "avg_latency_ms": round(avg_latency, 0),
                },
                "impact_estimate": f"Would avoid {int(error_rate * 100)}% error rate on {model}",
                "confidence": min(0.95, error_rate * 2),
            })
    return proposals


def run_analysis(cluster_id: str, signal_counts: Dict[str, int],
                 suppressed_counts: Dict[str, int], type_counts: Dict[str, int],
                 type_deduped: Dict[str, int], namespace_counts: Dict[str, int],
                 namespace_suppressed: Dict[str, int], model_stats: Dict[str, dict]) -> dict:
    """Run all analyzers and return combined proposals."""
    proposals = []
    proposals.extend(detect_noisy_namespaces(namespace_counts, namespace_suppressed, cluster_id))
    proposals.extend(detect_dedup_adjustments(type_counts, type_deduped, cluster_id))
    proposals.extend(detect_model_issues(model_stats, cluster_id))

    for p in proposals:
        p["status"] = "pending"
        p["created_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "cluster_id": cluster_id,
        "proposals": proposals,
        "total": len(proposals),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
