"""Inference client protocol and mock implementation."""

import random
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class InferenceResponse:
    model_name: str
    hardware_lane: str
    status: str
    output: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    ttft_ms: float
    tokens_per_second: float
    error: Optional[str] = None


@runtime_checkable
class InferenceClient(Protocol):
    def infer(self, model: str, prompt: str, max_tokens: int = 128) -> InferenceResponse: ...


MODEL_PROFILES = {
    "deepseek_r1_distill_qwen_14b_gaudi": {
        "hardware_lane": "gaudi3",
        "base_latency_ms": 800,
        "tokens_per_sec": 65,
        "ttft_base_ms": 120,
    },
    "phi4_gaudi": {
        "hardware_lane": "gaudi3",
        "base_latency_ms": 400,
        "tokens_per_sec": 90,
        "ttft_base_ms": 80,
    },
    "qwen3_14b_gaudi_a": {
        "hardware_lane": "gaudi3",
        "base_latency_ms": 600,
        "tokens_per_sec": 70,
        "ttft_base_ms": 100,
    },
    "qwen3_14b_gaudi_b": {
        "hardware_lane": "gaudi3",
        "base_latency_ms": 600,
        "tokens_per_sec": 70,
        "ttft_base_ms": 100,
    },
    # Micro agents — Xeon 6 CPU (OpenVINO, measured 15-28 tok/s)
    "granite_2b_cpu_xeon": {
        "hardware_lane": "xeon6",
        "base_latency_ms": 200,
        "tokens_per_sec": 25,
        "ttft_base_ms": 50,
    },
    "phi3_mini_cpu_xeon": {
        "hardware_lane": "xeon6",
        "base_latency_ms": 300,
        "tokens_per_sec": 18,
        "ttft_base_ms": 80,
    },
    "qwen25_3b_cpu_xeon": {
        "hardware_lane": "xeon6",
        "base_latency_ms": 250,
        "tokens_per_sec": 22,
        "ttft_base_ms": 60,
    },
    "llama_3_1_70b_q4_xeon": {
        "hardware_lane": "xeon6",
        "base_latency_ms": 5000,
        "tokens_per_sec": 6,
        "ttft_base_ms": 1500,
    },
}


class MockInferenceClient:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def infer(self, model: str, prompt: str, max_tokens: int = 128) -> InferenceResponse:
        profile = MODEL_PROFILES.get(model)
        if not profile:
            return InferenceResponse(
                model_name=model,
                hardware_lane="unknown",
                status="error",
                output="",
                tokens_in=0,
                tokens_out=0,
                latency_ms=0,
                ttft_ms=0,
                tokens_per_second=0,
                error=f"Unknown model: {model}",
            )

        jitter = self.rng.uniform(0.8, 1.2)
        tokens_in = max(1, len(prompt.split()) * 2)
        tokens_out = min(max_tokens, int(max_tokens * self.rng.uniform(0.7, 1.0)))
        tps = profile["tokens_per_sec"] * jitter
        generation_time_ms = (tokens_out / tps) * 1000
        ttft_ms = profile["ttft_base_ms"] * jitter
        latency_ms = ttft_ms + generation_time_ms

        return InferenceResponse(
            model_name=model,
            hardware_lane=profile["hardware_lane"],
            status="success",
            output=f"[mock output for {model}: {tokens_out} tokens]",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round(latency_ms, 2),
            ttft_ms=round(ttft_ms, 2),
            tokens_per_second=round(tps, 2),
        )
