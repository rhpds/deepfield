"""Monitoring tasks — poll Prometheus for cluster metrics."""

import logging

from celery import shared_task

logger = logging.getLogger("deepfield.tasks.monitoring")


@shared_task(bind=True, max_retries=1)
def poll_prometheus(self):
    """Scrape Prometheus for GPU utilization, pod counts, and latency."""
    try:
        import httpx

        prom_url = "http://prometheus.ecosystem-monitoring.svc:9090"
        queries = {
            "gpu_utilization": 'avg(DCGM_FI_DEV_GPU_UTIL{namespace=~"deepfield.*"})',
            "pod_count": 'count(kube_pod_info{namespace=~"deepfield.*"})',
            "inference_latency_p99": 'histogram_quantile(0.99, rate(inference_duration_seconds_bucket[5m]))',
        }

        results = {}
        with httpx.Client(timeout=10) as client:
            for name, query in queries.items():
                resp = client.get(
                    f"{prom_url}/api/v1/query",
                    params={"query": query},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("result", [])
                    results[name] = data
                else:
                    results[name] = {"error": resp.status_code}

        logger.info("Prometheus poll: %d metrics collected", len(results))
        return {"status": "ok", "metrics": results}
    except Exception as e:
        logger.warning("poll_prometheus failed: %s", e)
        return {"status": "error", "error": str(e)}
