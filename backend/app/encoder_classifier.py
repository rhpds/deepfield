"""Encoder classifier — runs zero-shot classification for micro tier agents.

Uses a small distilbert-mnli model for zero-shot classification of signals
that the cascade's nano tier can't handle with pattern matching alone.

Loaded lazily on first call. ~260MB model, ~150ms per classification on CPU.
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_classifier = None
_model_path = Path("/opt/app-root/src/models/encoder/zero-shot")


def _load():
    global _classifier
    if _classifier is not None:
        return _classifier

    if not _model_path.exists():
        log.warning("Encoder model not found at %s", _model_path)
        return None

    try:
        from transformers import pipeline
        t0 = time.monotonic()
        _classifier = pipeline(
            "zero-shot-classification",
            model=str(_model_path),
            device=-1,  # CPU
        )
        load_ms = (time.monotonic() - t0) * 1000
        log.info("Encoder classifier loaded in %.0fms from %s", load_ms, _model_path)
        return _classifier
    except Exception as e:
        log.warning("Failed to load encoder: %s", e)
        return None


def classify(text: str, labels: List[str]) -> Optional[Dict]:
    """Classify text against candidate labels.

    Returns: {"label": "best_match", "score": 0.95, "all_scores": {...}, "latency_ms": 42}
    """
    clf = _load()
    if clf is None:
        return None

    t0 = time.monotonic()
    try:
        result = clf(text, labels)
        elapsed = (time.monotonic() - t0) * 1000
        return {
            "label": result["labels"][0],
            "score": round(result["scores"][0], 3),
            "all_scores": {l: round(s, 3) for l, s in zip(result["labels"], result["scores"])},
            "latency_ms": round(elapsed),
        }
    except Exception as e:
        log.warning("Encoder classify failed: %s", e)
        return None


def classify_signal(signal_type: str, severity: str, content: dict) -> Optional[Dict]:
    """Classify a signal using domain-appropriate labels.

    Determines the right label set based on signal type and runs
    zero-shot classification.
    """
    text = f"{signal_type} {severity}: {content.get('message', '')} {content.get('resource_kind', '')}"

    # Route to appropriate label set
    if "crash" in signal_type or "oom" in signal_type or "restart" in signal_type:
        labels = ["configuration error", "resource exhaustion", "dependency failure", "application bug"]
    elif "unhealthy" in signal_type or "probe" in signal_type:
        labels = ["transient issue", "persistent failure", "misconfiguration", "resource pressure"]
    elif "schedule" in signal_type or "pending" in signal_type:
        labels = ["resource shortage", "node affinity conflict", "quota exceeded", "taint mismatch"]
    elif "network" in signal_type or "dns" in signal_type or "connection" in signal_type:
        labels = ["dns failure", "network policy", "service unavailable", "timeout"]
    elif "volume" in signal_type or "pvc" in signal_type or "disk" in signal_type:
        labels = ["storage full", "mount failure", "permission denied", "provisioning error"]
    elif "security" in signal_type or "auth" in signal_type or "forbidden" in signal_type:
        labels = ["unauthorized access", "expired credentials", "policy violation", "brute force"]
    else:
        labels = ["normal operation", "degraded performance", "failure", "security concern"]

    return classify(text, labels)


def is_available() -> bool:
    """Check if the encoder model is available."""
    return _model_path.exists()
