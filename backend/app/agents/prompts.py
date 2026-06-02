"""System prompts for specialized reasoning agents — loaded from YAML."""

import logging
import os
from pathlib import Path
from typing import Dict

logger = logging.getLogger("deepfield.prompts")

_prompt_cache: Dict[str, Dict] = {}
PROMPTS_DIR = str(Path(__file__).parent.parent / "prompts")


def load_prompt(name: str) -> Dict:
    """Load a versioned prompt from prompts/{name}.yaml (same pattern as StarGate)."""
    if name in _prompt_cache:
        return _prompt_cache[name]
    try:
        import yaml
        import re
        if not re.match(r'^[a-z_][a-z0-9_]*$', name):
            logger.warning("Invalid prompt name rejected: %s", name)
            return {}
        path = os.path.join(PROMPTS_DIR, f"{name}.yaml")
        if not os.path.exists(path):
            logger.warning(f"Prompt file not found: {path}")
            return {}
        with open(path) as f:
            prompt = yaml.safe_load(f)
        _prompt_cache[name] = prompt
        logger.info(f"Loaded prompt '{name}' v{prompt.get('version', '?')}")
        return prompt
    except Exception as e:
        logger.warning(f"Failed to load prompt '{name}': {e}")
        return {}


def get_system_prompt(name: str) -> str:
    """Get the system prompt text for a named prompt."""
    prompt = load_prompt(name)
    return prompt.get("system", "")


def get_prompt_version(name: str) -> str:
    """Get the version of a named prompt."""
    prompt = load_prompt(name)
    return prompt.get("version", "unknown")


# Backward-compatible constants — load from YAML at import time
def _load_system(name: str, fallback: str) -> str:
    prompt = load_prompt(name)
    return prompt.get("system", fallback)


TRIAGE_SYSTEM = _load_system("triage", 'You are an OpenShift Triage Agent. Respond with JSON only.')
RCA_SYSTEM = _load_system("rca", 'You are an OpenShift Root Cause Analysis Agent. Respond with JSON only.')
INCIDENT_SYSTEM = _load_system("incident", 'You are an OpenShift Incident Agent. Respond with JSON only.')
CORRELATION_SYSTEM = _load_system("correlation", 'You are an OpenShift Correlation Agent. Respond with JSON only.')
REMEDIATION_SYSTEM = _load_system("remediation", 'You are an OpenShift Remediation Agent. Respond with JSON only.')

# Micro-tier task type prompts
CLASSIFY_SIGNAL_SYSTEM = _load_system("classify_signal", 'You are a Signal Classification Agent. Classify the failure type. Respond with JSON only.')
CORRELATE_FINDINGS_SYSTEM = _load_system("correlate_findings", 'You are a Findings Correlation Agent. Find semantic relationships. Respond with JSON only.')
SUGGEST_REMEDIATION_SYSTEM = _load_system("suggest_remediation", 'You are a Quick Remediation Agent. Suggest a fix. Respond with JSON only.')
EXPLAIN_SIGNAL_SYSTEM = _load_system("explain_signal", 'You are a Signal Explanation Agent. Explain in plain language. Respond with JSON only.')
FILTER_NOISE_SYSTEM = _load_system("filter_noise", 'You are a Noise Filter Agent. Determine if actionable. Respond with JSON only.')


def format_evidence(evidence) -> str:
    """Format evidence into a structured prompt."""
    import json
    return json.dumps({
        "finding_type": evidence.finding_type,
        "severity": evidence.severity,
        "cluster": evidence.cluster,
        "namespace": evidence.namespace,
        "signals": evidence.signals,
        "context": evidence.context,
    }, indent=2)
