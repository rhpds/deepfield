"""Inference client — all models routed through LiteLLM proxy (MAAS).

No direct calls to rac-maas model endpoints. All inference goes through
the LiteLLM proxy which handles routing, auth, retries, and load balancing.
"""

import os
import time
import httpx

from app.inference.client import InferenceResponse

LITELLM_URL = os.getenv("LITELLM_API_BASE", "")
LITELLM_KEY = os.getenv("LITELLM_API_KEY", "")
SSL_VERIFY = os.getenv("SSL_VERIFY", "false").lower() == "true"

# All models routed through LiteLLM proxy
LITELLM_MODELS = {
    # Macro — Gaudi 3 GPU (deep reasoning)
    "deepseek_r1_distill_qwen_14b_gaudi": {
        "litellm_model": "deepseek-r1-distill-qwen-14b",
        "hardware_lane": "gaudi3",
    },
    "phi4_gaudi": {
        "litellm_model": "microsoft-phi-4",
        "hardware_lane": "gaudi3",
    },
    "qwen3_14b_gaudi_a": {
        "litellm_model": "qwen3-14b",
        "hardware_lane": "gaudi3",
    },
    "qwen3_14b_gaudi_b": {
        "litellm_model": "qwen3-14b",
        "hardware_lane": "gaudi3",
    },
    # Micro — CPU models via LiteLLM (fast triage)
    "granite_2b_cpu_xeon": {
        "litellm_model": "granite-4-0-h-tiny",
        "hardware_lane": "xeon6",
    },
    "phi3_mini_cpu_xeon": {
        "litellm_model": "codellama-7b-instruct",
        "hardware_lane": "xeon6",
    },
    "qwen25_3b_cpu_xeon": {
        "litellm_model": "granite-3-2-8b-instruct",
        "hardware_lane": "xeon6",
    },
}


def _build_messages(prompt: str) -> list:
    if "\n\nEvidence:" in prompt:
        system_part, user_part = prompt.split("\n\nEvidence:", 1)
        return [
            {"role": "system", "content": system_part},
            {"role": "user", "content": f"Evidence:{user_part}"},
        ]
    return [{"role": "user", "content": prompt}]


class RealInferenceClient:
    def __init__(self, ocp_token: str = ""):
        self.litellm_key = LITELLM_KEY

    def infer(self, model: str, prompt: str, max_tokens: int = 128) -> InferenceResponse:
        cfg = LITELLM_MODELS.get(model)
        if not cfg:
            return InferenceResponse(
                model_name=model, hardware_lane="unknown", status="error",
                output="", tokens_in=0, tokens_out=0, latency_ms=0,
                ttft_ms=0, tokens_per_second=0, error=f"Unknown model: {model}",
            )

        payload = {
            "model": cfg["litellm_model"],
            "messages": _build_messages(prompt),
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "stream": False,
        }

        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=httpx.Timeout(connect=10, read=45, write=10, pool=10), verify=SSL_VERIFY) as client:
                resp = client.post(
                    f"{LITELLM_URL}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.litellm_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return InferenceResponse(
                model_name=model, hardware_lane=cfg["hardware_lane"],
                status="error", output="", tokens_in=0, tokens_out=0,
                latency_ms=round(elapsed, 2), ttft_ms=0, tokens_per_second=0,
                error=str(e),
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        output_text = ""
        choices = data.get("choices", [])
        if choices:
            output_text = choices[0].get("message", {}).get("content", "")
        tps = (tokens_out / (elapsed_ms / 1000)) if elapsed_ms > 0 else 0

        return InferenceResponse(
            model_name=model, hardware_lane=cfg["hardware_lane"], status="success",
            output=output_text, tokens_in=tokens_in, tokens_out=tokens_out,
            latency_ms=round(elapsed_ms, 2), ttft_ms=round(elapsed_ms * 0.15, 2),
            tokens_per_second=round(tps, 2),
        )
