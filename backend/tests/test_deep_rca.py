"""Tests for two-pass deep root cause analysis.

Validates:
- JSON parsing with clean, think-tagged, markdown-fenced, and invalid input
- Two-pass flow: pass 1 success + pass 2 review merges correctly
- Fallback when pass 1 fails
- Fallback when pass 2 fails (returns pass 1 result unchanged)
- Original confidence preserved when review omits revised_confidence
"""

import json
from unittest.mock import patch
from uuid import uuid4

from app.inference.client import InferenceClient, InferenceResponse
from app.inference.deep_rca import _parse_json_output, run_deep_rca
from app.domain.models import CandidateFinding

# Mock the prompt config so tests don't need PyYAML or the YAML file
_MOCK_PROMPT_CONFIG = {
    "id": "deep_rca",
    "version": "1.0",
    "system": "You are a senior RCA agent. Respond with JSON only.",
    "review_system": "You are a senior SRE reviewer. Respond with JSON only.",
    "max_tokens": 2000,
    "review_max_tokens": 500,
}


# --- Helpers ---

def _make_finding(**overrides) -> CandidateFinding:
    defaults = dict(
        finding_id=uuid4(),
        clusters=[uuid4()],
        namespaces=["openshift-monitoring"],
        signal_ids=[uuid4() for _ in range(6)],
        finding_type="namespace_correlation",
        severity="critical",
        summary="test finding",
        evidence={
            "signals": [
                {"signal_type": "pod_oom_killed", "namespace": "openshift-monitoring",
                 "severity": "critical", "resource_name": "prometheus-0"},
            ],
        },
    )
    defaults.update(overrides)
    return CandidateFinding(**defaults)


RCA_JSON = {
    "root_cause": "OOM kill on prometheus-0",
    "category": "oom_kill",
    "evidence_chain": ["pod exceeded memory limit", "container killed by kernel"],
    "confidence": 0.85,
    "affected_resources": ["openshift-monitoring/prometheus-0"],
    "cross_system_impact": "alerting degraded",
    "remediation": {
        "priority": "immediate",
        "steps": ["increase memory limit"],
        "commands": ["oc set resources ..."],
        "risk": "low",
        "note": "requires restart",
    },
}

REVIEW_JSON = {
    "validation_score": 0.9,
    "evidence_gaps": ["no memory usage trend data"],
    "remediation_risks": ["restart will cause alert gap"],
    "recommended_investigation": ["check node memory pressure"],
    "revised_confidence": 0.75,
}


class _MockClient:
    """Configurable mock that returns preset responses per call index."""

    def __init__(self, responses: list[InferenceResponse]):
        self._responses = responses
        self._call_idx = 0
        self.calls: list[dict] = []

    def infer(self, model: str, prompt: str, max_tokens: int = 128) -> InferenceResponse:
        self.calls.append({"model": model, "prompt": prompt, "max_tokens": max_tokens})
        resp = self._responses[min(self._call_idx, len(self._responses) - 1)]
        self._call_idx += 1
        return resp


def _success_response(output: str, model: str = "test_model") -> InferenceResponse:
    return InferenceResponse(
        model_name=model, hardware_lane="gaudi3", status="success",
        output=output, tokens_in=100, tokens_out=50,
        latency_ms=500.0, ttft_ms=80.0, tokens_per_second=60.0,
    )


def _error_response(error: str = "timeout", model: str = "test_model") -> InferenceResponse:
    return InferenceResponse(
        model_name=model, hardware_lane="gaudi3", status="error",
        output="", tokens_in=0, tokens_out=0,
        latency_ms=0, ttft_ms=0, tokens_per_second=0, error=error,
    )


# --- _parse_json_output tests ---

class TestParseJsonOutput:

    def test_clean_json(self):
        result = _parse_json_output(json.dumps({"key": "value"}))
        assert result == {"key": "value"}

    def test_think_tagged_json(self):
        text = '<think>Let me analyze this carefully...</think>{"root_cause": "oom"}'
        result = _parse_json_output(text)
        assert result == {"root_cause": "oom"}

    def test_markdown_fenced_json(self):
        text = '```json\n{"root_cause": "oom"}\n```'
        result = _parse_json_output(text)
        assert result == {"root_cause": "oom"}

    def test_markdown_fenced_no_lang(self):
        text = '```\n{"root_cause": "oom"}\n```'
        result = _parse_json_output(text)
        assert result == {"root_cause": "oom"}

    def test_think_plus_fenced(self):
        text = '<think>reasoning here</think>\n```json\n{"confidence": 0.9}\n```'
        result = _parse_json_output(text)
        assert result == {"confidence": 0.9}

    def test_invalid_text_returns_none(self):
        result = _parse_json_output("This is not JSON at all.")
        assert result is None

    def test_json_embedded_in_text(self):
        text = 'Here is the analysis:\n{"root_cause": "config_error"}\nEnd of response.'
        result = _parse_json_output(text)
        assert result == {"root_cause": "config_error"}

    def test_empty_string(self):
        result = _parse_json_output("")
        assert result is None


# --- run_deep_rca tests ---

@patch("app.inference.deep_rca.load_prompt", return_value=_MOCK_PROMPT_CONFIG)
class TestRunDeepRca:

    def test_both_passes_success_revises_confidence(self, _mock_prompt):
        """Pass 1 returns RCA, pass 2 returns review -- confidence should be revised."""
        client = _MockClient([
            _success_response(json.dumps(RCA_JSON)),
            _success_response(json.dumps(REVIEW_JSON)),
        ])
        finding = _make_finding()
        result = run_deep_rca(finding, client)

        # Confidence revised by review
        assert result["confidence"] == 0.75
        # Review merged
        assert "review" in result
        assert result["review"]["validation_score"] == 0.9
        # Evidence gaps and remediation risks propagated
        assert result["evidence_gaps"] == ["no memory usage trend data"]
        assert result["remediation_risks"] == ["restart will cause alert gap"]
        # Two inference calls made
        assert len(client.calls) == 2

    def test_pass1_failure_returns_error(self, _mock_prompt):
        """When pass 1 fails, result should contain error info."""
        client = _MockClient([
            _error_response("model timeout"),
        ])
        finding = _make_finding()
        result = run_deep_rca(finding, client)

        assert result["error"] == "model timeout"
        assert result["pass"] == 1
        assert len(client.calls) == 1

    def test_pass2_failure_returns_pass1_unchanged(self, _mock_prompt):
        """When pass 2 fails, pass 1 result should be returned as-is."""
        client = _MockClient([
            _success_response(json.dumps(RCA_JSON)),
            _error_response("review model unavailable"),
        ])
        finding = _make_finding()
        result = run_deep_rca(finding, client)

        # Original confidence preserved
        assert result["confidence"] == 0.85
        # No review key
        assert "review" not in result
        assert len(client.calls) == 2

    def test_no_revised_confidence_preserves_original(self, _mock_prompt):
        """When review omits revised_confidence, original confidence is kept."""
        review_no_confidence = {
            "validation_score": 0.95,
            "evidence_gaps": [],
            "remediation_risks": [],
            "recommended_investigation": [],
        }
        client = _MockClient([
            _success_response(json.dumps(RCA_JSON)),
            _success_response(json.dumps(review_no_confidence)),
        ])
        finding = _make_finding()
        result = run_deep_rca(finding, client)

        # Original confidence kept
        assert result["confidence"] == 0.85
        # Review still merged
        assert "review" in result
        assert result["review"]["validation_score"] == 0.95

    def test_pass1_unparseable_output(self, _mock_prompt):
        """When pass 1 output is not valid JSON, return raw output."""
        client = _MockClient([
            _success_response("I cannot analyze this input."),
        ])
        finding = _make_finding()
        result = run_deep_rca(finding, client)

        assert result["raw_output"] == "I cannot analyze this input."
        assert result["pass"] == 1
        assert len(client.calls) == 1

    def test_pass2_unparseable_returns_pass1(self, _mock_prompt):
        """When pass 2 output is not valid JSON, pass 1 result returned."""
        client = _MockClient([
            _success_response(json.dumps(RCA_JSON)),
            _success_response("Not valid JSON review"),
        ])
        finding = _make_finding()
        result = run_deep_rca(finding, client)

        assert result["confidence"] == 0.85
        assert "review" not in result

    def test_uses_macro_model_for_pass1_micro_for_pass2(self, _mock_prompt):
        """Verify correct tier routing: macro for pass 1, micro for pass 2."""
        from app.inference.router import MACRO_MODELS, MICRO_MODELS
        client = _MockClient([
            _success_response(json.dumps(RCA_JSON)),
            _success_response(json.dumps(REVIEW_JSON)),
        ])
        finding = _make_finding()
        run_deep_rca(finding, client)

        assert client.calls[0]["model"] == MACRO_MODELS[0]
        assert client.calls[1]["model"] == MICRO_MODELS[0]
