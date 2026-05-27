"""Correlation Agent — cross-namespace/cluster pattern detection on Gaudi 3."""

import json
import time
from app.agents.base import AgentEvidence, AgentOutput
from app.agents.prompts import CORRELATION_SYSTEM, format_evidence
from app.inference.client import InferenceClient


class CorrelationReasoningAgent:
    agent_type = "correlation_reasoning"

    def __init__(self, client: InferenceClient, model: str = "phi4_gaudi"):
        self.client = client
        self.model = model

    def build_prompt(self, evidence: AgentEvidence) -> str:
        return f"{CORRELATION_SYSTEM}\n\nSignals across namespaces/clusters:\n{format_evidence(evidence)}"

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
            result = {"pattern": resp.output[:100], "common_cause": "unknown",
                     "confidence": 0.3}

        return AgentOutput(
            agent_type=self.agent_type, success=True, result=result,
            confidence=result.get("confidence", 0.5),
            model_used=self.model, latency_ms=round(latency, 1),
            tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
            raw_output=resp.output,
        )
