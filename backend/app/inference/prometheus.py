"""Polls Prometheus/Thanos for live vLLM and node metrics."""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import httpx


THANOS_URL = os.getenv("THANOS_URL", "")

QUERIES = {
    "requests_running": "vllm:num_requests_running",
    "requests_waiting": "vllm:num_requests_waiting",
    "kv_cache": "vllm:kv_cache_usage_perc",
    "gpu_cache": "vllm:gpu_cache_usage_perc",
    "tokens_rate": "rate(vllm:generation_tokens_total[30s])",
    "rps_rate": "rate(vllm:e2e_request_latency_seconds_count[30s])",
}


class PrometheusPoller:
    def __init__(self, ocp_token: str = ""):
        self.token = ocp_token or os.getenv("OCP_TOKEN", "")
        self._cache = {"models": {}, "nodes": {}, "available": False}
        self._lock = threading.Lock()
        self._polling = False
        self._client = httpx.Client(timeout=3.0, verify=False)
        self._start_background_poll()

    def _query(self, promql: str) -> list:
        try:
            resp = self._client.get(
                f"{THANOS_URL}/api/v1/query",
                params={"query": promql},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])
        except Exception:
            return []

    def _poll_once(self):
        models = {}

        # Run all queries in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {name: pool.submit(self._query, q) for name, q in QUERIES.items()}
            for name, f in futures.items():
                try:
                    results[name] = f.result(timeout=3)
                except Exception:
                    results[name] = []

        for r in results.get("requests_running", []):
            name = r["metric"].get("model_name", "unknown")
            models.setdefault(name, {})["requests_running"] = int(r["value"][1])

        for r in results.get("requests_waiting", []):
            name = r["metric"].get("model_name", "unknown")
            models.setdefault(name, {})["requests_waiting"] = int(r["value"][1])

        for r in results.get("kv_cache", []):
            name = r["metric"].get("model_name", "unknown")
            models.setdefault(name, {})["kv_cache_pct"] = round(float(r["value"][1]) * 100, 1)

        for r in results.get("gpu_cache", []):
            name = r["metric"].get("model_name", "unknown")
            models.setdefault(name, {})["gpu_cache_pct"] = round(float(r["value"][1]) * 100, 1)

        for r in results.get("tokens_rate", []):
            name = r["metric"].get("model_name", "unknown")
            models.setdefault(name, {})["tokens_per_sec_1m"] = round(float(r["value"][1]), 1)

        for r in results.get("rps_rate", []):
            name = r["metric"].get("model_name", "unknown")
            models.setdefault(name, {})["rps_1m"] = round(float(r["value"][1]), 2)

        with self._lock:
            self._cache = {"models": models, "nodes": {}, "available": bool(models), "ts": time.time()}

    def _start_background_poll(self):
        if self._polling:
            return
        self._polling = True

        def _loop():
            while self._polling:
                try:
                    self._poll_once()
                except Exception:
                    pass
                time.sleep(0.5)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def get_cluster_metrics(self) -> dict:
        with self._lock:
            return self._cache.copy()

    def stop(self):
        self._polling = False
