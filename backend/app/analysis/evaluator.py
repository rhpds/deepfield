"""EDD Evaluator — scores pipeline quality against rubrics using accumulated data.

Each rubric produces a score: healthy, warning, or failing.
Scores are based on real production metrics, not test fixtures.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict


@dataclass
class RubricConfig:
    compression_ratio_healthy: float = 50.0
    compression_ratio_warning: float = 10.0
    noise_reduction_healthy: float = 0.15
    noise_reduction_warning: float = 0.05
    suppress_rate_healthy_min: float = 0.05
    suppress_rate_healthy_max: float = 0.25
    finding_diversity_healthy: int = 3
    json_compliance_healthy: float = 0.90
    json_compliance_warning: float = 0.70
    taxonomy_match_healthy: float = 0.80
    taxonomy_match_warning: float = 0.50
    inconsistent_names_healthy: float = 0.05
    inconsistent_names_warning: float = 0.20
    unclassified_healthy: float = 0.10
    unclassified_warning: float = 0.30
    error_rate_healthy: float = 0.05
    error_rate_warning: float = 0.15
    rca_tokens_healthy: float = 300.0
    rca_tokens_warning: float = 100.0
    namespaces_healthy: int = 30
    namespaces_warning: int = 10
    agents_healthy: int = 4
    agents_warning: int = 2
    signal_types_healthy: int = 10
    signal_types_warning: int = 5


DEFAULT_CONFIG = RubricConfig()


def _score(checks: list) -> str:
    """Given a list of (name, level) tuples, return the worst level."""
    levels = [level for _, level in checks]
    if "failing" in levels:
        return "failing"
    if "warning" in levels:
        return "warning"
    return "healthy"


def score_compression(compression_ratio: float, dedup_rate: float,
                      suppress_rate: float, unique_finding_types: int) -> dict:
    checks = []
    if compression_ratio >= 50:
        checks.append(("compression_ratio", "healthy"))
    elif compression_ratio >= 10:
        checks.append(("compression_ratio", "warning"))
    else:
        checks.append(("compression_ratio", "failing"))

    # Combined noise reduction: dedup + suppress together
    noise_reduction = dedup_rate + suppress_rate
    if noise_reduction >= 0.15:
        checks.append(("dedup_rate", "healthy"))
    elif noise_reduction >= 0.05:
        checks.append(("dedup_rate", "warning"))
    else:
        checks.append(("dedup_rate", "failing"))

    if 0.05 <= suppress_rate <= 0.25:
        checks.append(("suppress_rate", "healthy"))
    elif suppress_rate < 0.05 or suppress_rate > 0.40:
        checks.append(("suppress_rate", "warning"))
    else:
        checks.append(("suppress_rate", "warning"))
    if suppress_rate > 0.60 or suppress_rate == 0:
        checks[-1] = ("suppress_rate", "failing")

    if unique_finding_types >= 3:
        checks.append(("finding_diversity", "healthy"))
    elif unique_finding_types >= 1:
        checks.append(("finding_diversity", "warning"))
    else:
        checks.append(("finding_diversity", "failing"))

    return {"score": _score(checks), "checks": checks}


def score_classification(json_compliance_rate: float, taxonomy_match_rate: float,
                         inconsistent_names_rate: float, unclassified_rate: float) -> dict:
    checks = []
    if json_compliance_rate >= 0.90:
        checks.append(("json_compliance", "healthy"))
    elif json_compliance_rate >= 0.70:
        checks.append(("json_compliance", "warning"))
    else:
        checks.append(("json_compliance", "failing"))

    if taxonomy_match_rate >= 0.80:
        checks.append(("taxonomy_match", "healthy"))
    elif taxonomy_match_rate >= 0.50:
        checks.append(("taxonomy_match", "warning"))
    else:
        checks.append(("taxonomy_match", "failing"))

    if inconsistent_names_rate < 0.05:
        checks.append(("inconsistent_names", "healthy"))
    elif inconsistent_names_rate < 0.20:
        checks.append(("inconsistent_names", "warning"))
    else:
        checks.append(("inconsistent_names", "failing"))

    if unclassified_rate < 0.10:
        checks.append(("unclassified", "healthy"))
    elif unclassified_rate < 0.30:
        checks.append(("unclassified", "warning"))
    else:
        checks.append(("unclassified", "failing"))

    return {"score": _score(checks), "checks": checks}


def score_inference(error_rate: float, avg_rca_tokens: float,
                    avg_micro_tokens: float, unique_root_causes: int) -> dict:
    checks = []
    if error_rate < 0.05:
        checks.append(("error_rate", "healthy"))
    elif error_rate < 0.15:
        checks.append(("error_rate", "warning"))
    else:
        checks.append(("error_rate", "failing"))

    if avg_rca_tokens >= 300:
        checks.append(("rca_depth", "healthy"))
    elif avg_rca_tokens >= 100:
        checks.append(("rca_depth", "warning"))
    else:
        checks.append(("rca_depth", "failing"))

    if 50 <= avg_micro_tokens <= 200:
        checks.append(("micro_output", "healthy"))
    else:
        checks.append(("micro_output", "warning"))

    if unique_root_causes >= 5:
        checks.append(("rca_diversity", "healthy"))
    elif unique_root_causes >= 2:
        checks.append(("rca_diversity", "warning"))
    else:
        checks.append(("rca_diversity", "failing"))

    return {"score": _score(checks), "checks": checks}


def score_coverage(namespaces_monitored: int, active_agents: int,
                   signal_type_diversity: int, critical_signals_today: int) -> dict:
    checks = []
    if namespaces_monitored >= 30:
        checks.append(("namespaces", "healthy"))
    elif namespaces_monitored >= 10:
        checks.append(("namespaces", "warning"))
    else:
        checks.append(("namespaces", "failing"))

    if active_agents >= 8:
        checks.append(("agents", "healthy"))
    elif active_agents >= 4:
        checks.append(("agents", "warning"))
    else:
        checks.append(("agents", "failing"))

    if signal_type_diversity >= 10:
        checks.append(("signal_types", "healthy"))
    elif signal_type_diversity >= 5:
        checks.append(("signal_types", "warning"))
    else:
        checks.append(("signal_types", "failing"))

    if critical_signals_today > 0:
        checks.append(("critical_detection", "healthy"))
    else:
        checks.append(("critical_detection", "warning"))

    return {"score": _score(checks), "checks": checks}


def score_safety(new_types_suppressed: int, cross_resource_dedup: int,
                 critical_deduped: int) -> dict:
    checks = []
    if new_types_suppressed == 0:
        checks.append(("type_suppression", "healthy"))
    else:
        checks.append(("type_suppression", "failing"))

    if cross_resource_dedup == 0:
        checks.append(("cross_resource", "healthy"))
    else:
        checks.append(("cross_resource", "failing"))

    if critical_deduped == 0:
        checks.append(("critical_dedup", "healthy"))
    else:
        checks.append(("critical_dedup", "failing"))

    return {"score": _score(checks), "checks": checks}


def evaluate_pipeline(cluster_id: str, **kwargs) -> dict:
    """Run all EDD rubrics and return overall assessment."""
    rubrics = {
        "compression_quality": score_compression(
            compression_ratio=kwargs.get("compression_ratio", 0),
            dedup_rate=kwargs.get("dedup_rate", 0),
            suppress_rate=kwargs.get("suppress_rate", 0),
            unique_finding_types=kwargs.get("unique_finding_types", 0),
        ),
        "classification_accuracy": score_classification(
            json_compliance_rate=kwargs.get("json_compliance_rate", 0),
            taxonomy_match_rate=kwargs.get("taxonomy_match_rate", 0),
            inconsistent_names_rate=kwargs.get("inconsistent_names_rate", 0),
            unclassified_rate=kwargs.get("unclassified_rate", 0),
        ),
        "inference_value": score_inference(
            error_rate=kwargs.get("error_rate", 0),
            avg_rca_tokens=kwargs.get("avg_rca_tokens", 0),
            avg_micro_tokens=kwargs.get("avg_micro_tokens", 0),
            unique_root_causes=kwargs.get("unique_root_causes", 0),
        ),
        "signal_coverage": score_coverage(
            namespaces_monitored=kwargs.get("namespaces_monitored", 0),
            active_agents=kwargs.get("active_agents", 0),
            signal_type_diversity=kwargs.get("signal_type_diversity", 0),
            critical_signals_today=kwargs.get("critical_signals_today", 0),
        ),
        "tuning_safety": score_safety(
            new_types_suppressed=kwargs.get("new_types_suppressed", 0),
            cross_resource_dedup=kwargs.get("cross_resource_dedup", 0),
            critical_deduped=kwargs.get("critical_deduped", 0),
        ),
    }

    scores = [r["score"] for r in rubrics.values()]
    if "failing" in scores:
        overall = "failing"
    elif "warning" in scores:
        overall = "warning"
    else:
        overall = "healthy"

    return {
        "cluster_id": cluster_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rubrics": rubrics,
        "overall": overall,
    }
