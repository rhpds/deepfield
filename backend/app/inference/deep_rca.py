"""Two-pass deep root cause analysis.

Pass 1: Deep RCA on macro tier (Gaudi 3 -- DeepSeek or Phi-4)
Pass 2: Critical review on micro tier (Granite on Xeon 6)

The review pass catches hallucinated resource names, unsupported
confidence claims, and risky remediation commands.
"""

import json
import logging
import re
from typing import Optional

from app.agents.prompts import load_prompt
from app.inference.client import InferenceClient, InferenceResponse
from app.inference.router import MACRO_MODELS, MICRO_MODELS
from app.routing.signal_router import _build_evidence_block

logger = logging.getLogger("deepfield.deep_rca")


def run_deep_rca(finding, client: InferenceClient) -> dict:
    """Two-pass RCA: initial analysis on macro tier + critical review on micro tier."""
    prompt_config = load_prompt("deep_rca")
    if not prompt_config:
        logger.warning("deep_rca prompt not found, falling back to single-pass")
        return {}

    evidence_block = _build_evidence_block(finding)
    evidence_json = json.dumps(evidence_block, indent=2)

    # Pass 1: Deep RCA on macro tier
    system_prompt = prompt_config.get("system", "")
    rca_prompt = f"{system_prompt}\n\nEvidence:\n{evidence_json}"
    max_tokens = prompt_config.get("max_tokens", 2000)

    macro_model = MACRO_MODELS[0]  # Use first available macro model
    rca_response = client.infer(model=macro_model, prompt=rca_prompt, max_tokens=max_tokens)

    if rca_response.status != "success":
        logger.warning("Deep RCA pass 1 failed: %s", rca_response.error)
        return {"error": rca_response.error, "pass": 1}

    rca_output = _parse_json_output(rca_response.output)
    if not rca_output:
        logger.warning("Deep RCA pass 1 returned unparseable output")
        return {"raw_output": rca_response.output, "pass": 1}

    # Pass 2: Critical review on micro tier
    review_system = prompt_config.get("review_system", "")
    if not review_system:
        return rca_output

    review_prompt = (
        f"{review_system}\n\n"
        f"Original Evidence:\n{evidence_json}\n\n"
        f"Proposed RCA:\n{json.dumps(rca_output, indent=2)}"
    )
    review_max_tokens = prompt_config.get("review_max_tokens", 500)

    micro_model = MICRO_MODELS[0]  # Use first available micro model
    review_response = client.infer(model=micro_model, prompt=review_prompt, max_tokens=review_max_tokens)

    if review_response.status != "success":
        logger.debug("Deep RCA review pass failed (non-critical): %s", review_response.error)
        return rca_output

    review_output = _parse_json_output(review_response.output)
    if not review_output:
        logger.debug("Deep RCA review returned unparseable output")
        return rca_output

    # Merge review into RCA result
    if review_output.get("revised_confidence") is not None:
        rca_output["confidence"] = review_output["revised_confidence"]
    rca_output["review"] = review_output
    rca_output["evidence_gaps"] = review_output.get("evidence_gaps", [])
    rca_output["remediation_risks"] = review_output.get("remediation_risks", [])

    return rca_output


def _parse_json_output(output: str) -> Optional[dict]:
    """Parse JSON from LLM output, handling think tags and markdown fences."""
    # Strip <think>...</think> tags
    cleaned = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL).strip()
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        # Try to find JSON object in the text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                pass
    return None
