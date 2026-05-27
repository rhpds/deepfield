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
