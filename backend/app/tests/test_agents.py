"""TDD tests for specialized reasoning agents."""

from app.agents.base import AgentEvidence, AgentOutput
from app.agents.triage import TriageAgent
from app.agents.rca import RCAAgent
from app.agents.incident import IncidentAgent
from app.agents.correlation_agent import CorrelationReasoningAgent
from app.agents.remediation import RemediationAgent
from app.inference.client import MockInferenceClient


def _evidence(severity="high", finding_type="namespace_correlation"):
    return AgentEvidence(
        finding_type=finding_type,
        severity=severity,
        cluster="infra01",
        namespace="deepfield-chaos",
        signals=[
            {"type": "pod_crashloop", "resource": "crashloop-app-abc", "restartCount": 15},
            {"type": "pod_imagepullbackoff", "resource": "bad-image-xyz", "reason": "ImagePullBackOff"},
        ],
        context={"signal_count": 2},
    )


def test_triage_agent_returns_structured_output():
    client = MockInferenceClient(seed=42)
    agent = TriageAgent(client)
    result = agent.analyze(_evidence())
    assert isinstance(result, AgentOutput)
    assert result.agent_type == "triage"
    assert result.success is True
    assert result.model_used != ""
    assert result.latency_ms >= 0


def test_triage_agent_builds_prompt():
    client = MockInferenceClient(seed=42)
    agent = TriageAgent(client)
    prompt = agent.build_prompt(_evidence())
    assert "Triage Agent" in prompt
    assert "pod_crashloop" in prompt
    assert "infra01" in prompt


def test_rca_agent_returns_structured_output():
    client = MockInferenceClient(seed=42)
    agent = RCAAgent(client)
    result = agent.analyze(_evidence())
    assert isinstance(result, AgentOutput)
    assert result.agent_type == "rca"
    assert result.success is True
    assert result.tokens_out > 0


def test_rca_agent_builds_prompt_with_evidence():
    client = MockInferenceClient(seed=42)
    agent = RCAAgent(client)
    prompt = agent.build_prompt(_evidence())
    assert "Root Cause Analysis" in prompt
    assert "deepfield-chaos" in prompt


def test_incident_agent_returns_structured_output():
    client = MockInferenceClient(seed=42)
    agent = IncidentAgent(client)
    result = agent.analyze(_evidence())
    assert isinstance(result, AgentOutput)
    assert result.agent_type == "incident"
    assert result.success is True


def test_correlation_agent_returns_structured_output():
    client = MockInferenceClient(seed=42)
    agent = CorrelationReasoningAgent(client)
    result = agent.analyze(_evidence(finding_type="cross_cluster_correlation"))
    assert isinstance(result, AgentOutput)
    assert result.agent_type == "correlation_reasoning"
    assert result.success is True


def test_remediation_agent_returns_structured_output():
    client = MockInferenceClient(seed=42)
    agent = RemediationAgent(client)
    result = agent.analyze(_evidence())
    assert isinstance(result, AgentOutput)
    assert result.agent_type == "remediation"
    assert result.success is True


def test_all_agents_handle_error_gracefully():
    """Agents should not crash on inference errors."""
    client = MockInferenceClient(seed=42)
    evidence = _evidence()
    for AgentClass in [TriageAgent, RCAAgent, IncidentAgent, CorrelationReasoningAgent, RemediationAgent]:
        agent = AgentClass(client, model="nonexistent_model")
        result = agent.analyze(evidence)
        assert isinstance(result, AgentOutput)
        assert result.success is False
        assert result.error is not None
