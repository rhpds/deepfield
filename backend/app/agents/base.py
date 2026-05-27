"""Base protocol for specialized reasoning agents."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class AgentEvidence:
    """Structured evidence passed to reasoning agents."""
    finding_type: str
    severity: str
    cluster: str
    namespace: str
    signals: List[Dict[str, Any]]
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentOutput:
    """Structured output from a reasoning agent."""
    agent_type: str
    success: bool
    result: Dict[str, Any]
    confidence: float = 0.0
    model_used: str = ""
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    raw_output: str = ""
    error: Optional[str] = None


@runtime_checkable
class ReasoningAgent(Protocol):
    agent_type: str

    def analyze(self, evidence: AgentEvidence) -> AgentOutput: ...

    def build_prompt(self, evidence: AgentEvidence) -> str: ...
