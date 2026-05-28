"""Failure classifier nano-agent — deterministic regex pattern matching
against known K8s failure classes BEFORE sending signals to the LLM.

Loads failure class patterns from a local YAML file (copied from
StarGate's failure-classes/k8s-events.yaml). If a signal's evidence
message matches a known pattern, the signal is classified immediately
with confidence=1.0, skipping the expensive LLM call.

Fallback: can also load patterns from StarGate's corpus API at
GET /dashboard/corpus/classes?source=k8s_events
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.domain.models import FilterDecision, NormalizedSignal

name = "FailureClassifierAgent"

# ── Pattern loading ──────────────────────────────────────────────────

_YAML_PATH = Path(__file__).parent / "failure_classes" / "k8s-events.yaml"
_compiled_classes: Optional[Dict[str, Dict[str, Any]]] = None


def _load_classes_from_yaml(path: Path = _YAML_PATH) -> Dict[str, Dict[str, Any]]:
    """Load and compile failure class patterns from YAML."""
    with open(path) as f:
        data = yaml.safe_load(f)

    classes = data.get("classes", {})
    compiled = {}
    for class_name, class_def in classes.items():
        pattern_str = class_def.get("pattern", "")
        try:
            compiled[class_name] = {
                "regex": re.compile(pattern_str, re.IGNORECASE),
                "severity": class_def.get("severity", "medium"),
                "remediation": class_def.get("remediation", []),
                "pattern": pattern_str,
            }
        except re.error:
            # Skip malformed patterns
            continue

    return compiled


def _get_compiled_classes() -> Dict[str, Dict[str, Any]]:
    """Return cached compiled failure classes (lazy singleton)."""
    global _compiled_classes
    if _compiled_classes is None:
        _compiled_classes = _load_classes_from_yaml()
    return _compiled_classes


def get_failure_classes() -> Dict[str, Dict[str, Any]]:
    """Public accessor for loaded failure classes (used by tests)."""
    return _get_compiled_classes()


# ── Signal matching ──────────────────────────────────────────────────


def _extract_message(signal: NormalizedSignal) -> str:
    """Extract the text to match against from a signal's evidence and labels."""
    parts = []
    if "message" in signal.evidence:
        parts.append(str(signal.evidence["message"]))
    if "reason" in signal.evidence:
        parts.append(str(signal.evidence["reason"]))
    if "raw_message" in signal.evidence:
        parts.append(str(signal.evidence["raw_message"]))
    # Also check labels for event reason
    if "event_reason" in signal.labels:
        parts.append(str(signal.labels["event_reason"]))
    return " ".join(parts)


def _match_signal(signal: NormalizedSignal) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Try to match a signal against all failure class patterns.

    Returns (class_name, class_def) on first match, or None.
    """
    text = _extract_message(signal)
    if not text.strip():
        return None

    for class_name, class_def in _get_compiled_classes().items():
        if class_def["regex"].search(text):
            return class_name, class_def

    return None


# ── Filter entry point ──────────────────────────────────────────────


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    """Run pattern matching against known failure classes for each signal.

    - If matched: return enrich decision with failure_class, confidence=1.0,
      severity, and remediation steps.
    - If not matched: return keep/pass decision so downstream agents
      (or the LLM) can handle it.
    """
    decisions: List[FilterDecision] = []

    for signal in signals:
        match = _match_signal(signal)
        if match:
            class_name, class_def = match
            decisions.append(FilterDecision(
                signal_id=signal.signal_id,
                filter_name=name,
                outcome="enrich",
                reason_code=f"failure_class:{class_name}",
                evidence={
                    "action": "classify",
                    "failure_class": class_name,
                    "confidence": 1.0,
                    "source": "deterministic_pattern",
                    "class_severity": class_def["severity"],
                    "remediation": class_def["remediation"],
                    "matched_pattern": class_def["pattern"],
                },
            ))
        else:
            decisions.append(FilterDecision(
                signal_id=signal.signal_id,
                filter_name=name,
                outcome="keep",
                reason_code="no_pattern_match",
                evidence={
                    "action": "pass",
                    "note": "no known failure class matched — defer to LLM",
                },
            ))

    return decisions
