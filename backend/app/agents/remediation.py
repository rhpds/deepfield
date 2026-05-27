"""Remediation Agent — suggests fix steps (read-only, never executes)."""

import json
import time
from app.agents.base import AgentEvidence, AgentOutput
from app.agents.prompts import REMEDIATION_SYSTEM, format_evidence
from app.inference.client import InferenceClient


class RemediationAgent:
    agent_type = "remediation"

    def __init__(self, client: InferenceClient, model: str = "qwen3_14b_gaudi_b"):
        self.client = client
        self.model = model

    def build_prompt(self, evidence: AgentEvidence) -> str:
        return f"{REMEDIATION_SYSTEM}\n\nRCA + Incident Context:\n{format_evidence(evidence)}"

    def analyze(self, evidence: AgentEvidence) -> AgentOutput:
        prompt = self.build_prompt(evidence)
        t0 = time.monotonic()
        resp = self.client.infer(model=self.model, prompt=prompt, max_tokens=256)
        latency = (time.monotonic() - t0) * 1000

        if resp.status != "success":
            return AgentOutput(agent_type=self.agent_type, success=False, result={},
                             error=resp.error, model_used=self.model, latency_ms=latency)

        try:
            result = json.loads(resp.output.strip())
        except json.JSONDecodeError:
            result = {"action": resp.output[:100], "steps": [], "commands": [],
                     "risk": "unknown", "reversible": True}

        return AgentOutput(
            agent_type=self.agent_type, success=True, result=result,
            confidence=0.6,
            model_used=self.model, latency_ms=round(latency, 1),
            tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
            raw_output=resp.output,
        )
