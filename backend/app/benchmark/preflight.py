"""Preflight checks and warmup for benchmark runs."""

import time
import os
import httpx

from app.inference.adapters import MODEL_ENDPOINTS


def run_preflight(ocp_token: str = "") -> dict:
    token = ocp_token or os.getenv("OCP_TOKEN", "")
    results = {
        "status": "running",
        "token_valid": False,
        "prometheus_connected": False,
        "models": {},
        "warnings": [],
        "ready": False,
    }

    # Check token
    if not token:
        results["warnings"].append("OCP_TOKEN not set")
        results["status"] = "failed"
        return results
    results["token_valid"] = True

    # Check each model endpoint
    for model_key, endpoint in MODEL_ENDPOINTS.items():
        model_result = {
            "url": endpoint["url"],
            "model_name": endpoint["model_name"],
            "hardware_lane": endpoint["hardware_lane"],
            "reachable": False,
            "latency_ms": 0,
            "error": None,
        }
        try:
            with httpx.Client(timeout=10.0, verify=False) as client:
                t0 = time.monotonic()
                resp = client.get(
                    f"{endpoint['url']}/v1/models",
                    headers={"Authorization": f"Bearer {token}"},
                )
                latency = (time.monotonic() - t0) * 1000
                resp.raise_for_status()
                model_result["reachable"] = True
                model_result["latency_ms"] = round(latency, 1)
        except Exception as e:
            model_result["error"] = str(e)[:200]
            results["warnings"].append(f"{model_key}: {str(e)[:100]}")

        results["models"][model_key] = model_result

    # Check Prometheus
    try:
        from app.inference.prometheus import PrometheusPoller
        poller = PrometheusPoller(ocp_token=token)
        time.sleep(1)
        metrics = poller.get_cluster_metrics()
        results["prometheus_connected"] = metrics.get("available", False)
        results["prometheus_model_count"] = len(metrics.get("models", {}))
        poller.stop()
    except Exception as e:
        results["warnings"].append(f"Prometheus: {str(e)[:100]}")

    # Check cluster load
    reachable_count = sum(1 for m in results["models"].values() if m["reachable"])
    total_count = len(results["models"])
    results["reachable_count"] = reachable_count
    results["total_count"] = total_count
    results["ready"] = reachable_count >= 3 and results["token_valid"]
    results["status"] = "passed" if results["ready"] else "failed"

    return results


def run_warmup(ocp_token: str = "") -> dict:
    token = ocp_token or os.getenv("OCP_TOKEN", "")
    results = {"models": {}, "total_ms": 0}
    start = time.monotonic()

    for model_key, endpoint in MODEL_ENDPOINTS.items():
        warmup = {"status": "pending", "latency_ms": 0, "tokens_out": 0, "error": None}
        try:
            with httpx.Client(timeout=30.0, verify=False) as client:
                t0 = time.monotonic()
                resp = client.post(
                    f"{endpoint['url']}/v1/chat/completions",
                    json={
                        "model": endpoint["model_name"],
                        "messages": [{"role": "user", "content": "Say OK"}],
                        "max_tokens": 5,
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                latency = (time.monotonic() - t0) * 1000
                resp.raise_for_status()
                data = resp.json()
                tokens = data.get("usage", {}).get("completion_tokens", 0)
                warmup["status"] = "ok"
                warmup["latency_ms"] = round(latency, 1)
                warmup["tokens_out"] = tokens
        except Exception as e:
            warmup["status"] = "error"
            warmup["error"] = str(e)[:200]

        results["models"][model_key] = warmup

    results["total_ms"] = round((time.monotonic() - start) * 1000, 1)
    return results
