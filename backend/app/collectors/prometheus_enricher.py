"""Prometheus enricher — adds resource metrics to findings before LLM inference.

Called on-demand, not continuously. Queries are cached to avoid
hammering Thanos. Each cluster has its own Thanos endpoint.
"""

import logging
import os
import time
import threading
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL = 300
_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()


class PrometheusEnricher:
    def __init__(self, cluster_configs: list):
        self._endpoints: Dict[str, dict] = {}
        self._token = os.getenv("ALERTMANAGER_TOKEN", "")

        for cfg in cluster_configs:
            name = cfg.get("name", "")
            api_url = cfg.get("api_url", "")
            token = cfg.get("token", "")
            if not name or not api_url:
                continue
            domain = api_url.replace("https://api.", "").replace(":6443", "")
            thanos = f"https://thanos-querier-openshift-monitoring.apps.{domain}"
            self._endpoints[name] = {"url": thanos, "token": token}

        if self._endpoints:
            logger.info("PrometheusEnricher: %d clusters configured", len(self._endpoints))

    def _query(self, cluster: str, promql: str) -> Optional[list]:
        ep = self._endpoints.get(cluster)
        if not ep:
            return None

        cache_key = f"{cluster}:{promql}"
        with _cache_lock:
            if cache_key in _cache:
                data, ts = _cache[cache_key]
                if time.monotonic() - ts < CACHE_TTL:
                    return data

        try:
            with httpx.Client(timeout=10.0, verify=False) as client:
                resp = client.get(
                    f"{ep['url']}/api/v1/query",
                    params={"query": promql},
                    headers={"Authorization": f"Bearer {ep['token']}"},
                )
                if resp.status_code != 200:
                    return None
                results = resp.json().get("data", {}).get("result", [])
                with _cache_lock:
                    _cache[cache_key] = (results, time.monotonic())
                    if len(_cache) > 500:
                        oldest = min(_cache, key=lambda k: _cache[k][1])
                        del _cache[oldest]
                return results
        except Exception:
            return None

    def enrich_namespace(self, cluster: str, namespace: str) -> dict:
        """Get resource metrics for a namespace. Returns dict to merge into evidence."""
        metrics = {}

        # Pod memory usage in namespace
        results = self._query(cluster,
            f'sum(container_memory_working_set_bytes{{namespace="{namespace}"}}) / '
            f'sum(kube_pod_container_resource_limits{{namespace="{namespace}",resource="memory"}})')
        if results:
            try:
                pct = float(results[0]["value"][1]) * 100
                metrics["memory_usage_pct"] = round(pct, 1)
            except (IndexError, ValueError, KeyError):
                pass

        # Pod CPU usage in namespace
        results = self._query(cluster,
            f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}"}}[5m])) / '
            f'sum(kube_pod_container_resource_limits{{namespace="{namespace}",resource="cpu"}})')
        if results:
            try:
                pct = float(results[0]["value"][1]) * 100
                metrics["cpu_usage_pct"] = round(pct, 1)
            except (IndexError, ValueError, KeyError):
                pass

        # Restart count in namespace
        results = self._query(cluster,
            f'sum(kube_pod_container_status_restarts_total{{namespace="{namespace}"}})')
        if results:
            try:
                metrics["total_restarts"] = int(float(results[0]["value"][1]))
            except (IndexError, ValueError, KeyError):
                pass

        # OOM kills in namespace
        results = self._query(cluster,
            f'sum(kube_pod_container_status_last_terminated_reason{{namespace="{namespace}",reason="OOMKilled"}})')
        if results:
            try:
                val = int(float(results[0]["value"][1]))
                if val > 0:
                    metrics["oom_killed_containers"] = val
            except (IndexError, ValueError, KeyError):
                pass

        # Pod count by status
        results = self._query(cluster,
            f'sum by(phase)(kube_pod_status_phase{{namespace="{namespace}"}} == 1)')
        if results:
            for r in results:
                phase = r.get("metric", {}).get("phase", "")
                try:
                    count = int(float(r["value"][1]))
                    if count > 0:
                        metrics[f"pods_{phase.lower()}"] = count
                except (IndexError, ValueError, KeyError):
                    pass

        return metrics
