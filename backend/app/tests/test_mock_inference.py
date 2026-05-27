"""Tests for mock inference client."""

from app.inference.client import MockInferenceClient


def test_mock_inference_client_returns_deterministic_metrics():
    c1 = MockInferenceClient(seed=42)
    c2 = MockInferenceClient(seed=42)
    r1 = c1.infer("phi4_gaudi", "Summarize this cluster state.", max_tokens=64)
    r2 = c2.infer("phi4_gaudi", "Summarize this cluster state.", max_tokens=64)
    assert r1.status == "success"
    assert r1.latency_ms == r2.latency_ms
    assert r1.tokens_out == r2.tokens_out
    assert r1.tokens_per_second == r2.tokens_per_second
    assert r1.hardware_lane == "gaudi3"
    assert r1.tokens_in > 0
    assert r1.tokens_out > 0
