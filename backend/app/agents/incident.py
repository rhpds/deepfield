"""Incident Agent — scope and blast radius assessment on Gaudi 3."""

import json
import time
from app.agents.base import AgentEvidence, AgentOutput
from app.agents.prompts import INCIDENT_SYSTEM, format_evidence
from app.inference.client import InferenceClient


class IncidentAgent:
    agent_type = "incident"

    def __init__(self, client: InferenceClient, model: str = "qwen3_14b_gaudi_a"):
        self.client = client
        self.model = model

    def build_prompt(self, evidence: AgentEvidence) -> str:
        return f"{INCIDENT_SYSTEM}\n\nCorrelated Findings:\n{format_evidence(evidence)}"

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
            result = {"scope": "unknown", "affected_services": [],
                     "blast_radius": resp.output[:100], "priority": "P3"}

        return AgentOutput(
            agent_type=self.agent_type, success=True, result=result,
            confidence=0.7,
            model_used=self.model, latency_ms=round(latency, 1),
            tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
            raw_output=resp.output,
        )
