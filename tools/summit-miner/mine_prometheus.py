#!/usr/bin/env python3
"""Mine Prometheus/Thanos metrics from Summit week (May 5-8, 2026).

Run from a machine with oc access to infra01:
    export THANOS_TOKEN=$(oc create token deepfield-alertmanager -n deepfield --duration=1h)
    python3 tools/summit-miner/mine_prometheus.py

Outputs JSON files to data/summit-2026/prometheus/
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)

THANOS_EXTERNAL = os.getenv("THANOS_URL", "")
if not THANOS_EXTERNAL:
    print("Set THANOS_URL to your Thanos Querier endpoint:")
    print("  export THANOS_URL=https://thanos-querier-openshift-monitoring.apps.<cluster>/")
    sys.exit(1)
TOKEN = os.getenv("THANOS_TOKEN", "")

SUMMIT_START = "2026-05-05T00:00:00Z"
SUMMIT_END = "2026-05-08T23:59:59Z"

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "summit-2026" / "prometheus"

QUERIES = {
    "pod_count": {
        "query": "count(kube_pod_info)",
        "step": "15m",
        "description": "Total pod count across cluster",
    },
    "pod_phases": {
        "query": "sum by(phase)(kube_pod_status_phase == 1)",
        "step": "15m",
        "description": "Pod count by phase (Running, Pending, Failed, etc.)",
    },
    "node_memory_available_pct": {
        "query": "100 * sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)",
        "step": "15m",
        "description": "Cluster memory available percentage",
    },
    "node_cpu_usage_pct": {
        "query": "100 * (1 - avg(rate(node_cpu_seconds_total{mode='idle'}[5m])))",
        "step": "15m",
        "description": "Cluster CPU usage percentage",
    },
    "node_count": {
        "query": "count(kube_node_info)",
        "step": "1h",
        "description": "Total node count",
    },
    "node_conditions": {
        "query": "sum by(condition)(kube_node_status_condition{status='true'})",
        "step": "1h",
        "description": "Node conditions (Ready, MemoryPressure, DiskPressure, etc.)",
    },
    "container_restarts_by_ns": {
        "query": "sum by(namespace)(increase(kube_pod_container_status_restarts_total[1h]))",
        "step": "1h",
        "description": "Container restarts per namespace per hour",
    },
    "container_waiting_reasons": {
        "query": "sum by(reason)(kube_pod_container_status_waiting_reason)",
        "step": "30m",
        "description": "Container waiting reasons (CrashLoopBackOff, ImagePullBackOff, etc.)",
    },
    "container_terminated_reasons": {
        "query": "sum by(reason)(kube_pod_container_status_terminated_reason)",
        "step": "30m",
        "description": "Container termination reasons (OOMKilled, Error, Completed, etc.)",
    },
    "network_rx_mbps": {
        "query": "sum(rate(container_network_receive_bytes_total[5m])) / 1024 / 1024",
        "step": "15m",
        "description": "Cluster network receive rate (MB/s)",
    },
    "network_tx_mbps": {
        "query": "sum(rate(container_network_transmit_bytes_total[5m])) / 1024 / 1024",
        "step": "15m",
        "description": "Cluster network transmit rate (MB/s)",
    },
    "disk_usage_pct": {
        "query": "100 * (1 - sum(node_filesystem_avail_bytes{mountpoint='/'}) / sum(node_filesystem_size_bytes{mountpoint='/'}))",
        "step": "1h",
        "description": "Root filesystem usage percentage",
    },
    "etcd_leader_changes": {
        "query": "sum(increase(etcd_server_leader_changes_seen_total[1h]))",
        "step": "1h",
        "description": "etcd leader changes per hour",
    },
    "api_request_rate": {
        "query": "sum(rate(apiserver_request_total[5m]))",
        "step": "15m",
        "description": "Kubernetes API request rate",
    },
    "api_errors": {
        "query": "sum(rate(apiserver_request_total{code=~'5..'}[5m]))",
        "step": "15m",
        "description": "Kubernetes API 5xx error rate",
    },
    "oom_events": {
        "query": "sum(increase(container_oom_events_total[1h]))",
        "step": "1h",
        "description": "OOM kill events per hour",
    },
    "image_pull_failures": {
        "query": "sum(increase(container_runtime_crio_image_pulls_failure_total[1h]))",
        "step": "1h",
        "description": "Image pull failures per hour",
    },
    "up_targets": {
        "query": "count(up == 1)",
        "step": "1h",
        "description": "Number of healthy scrape targets",
    },
    "down_targets": {
        "query": "count(up == 0)",
        "step": "1h",
        "description": "Number of down scrape targets",
    },
}


def query_range(client: httpx.Client, query: str, step: str) -> dict:
    resp = client.get(
        f"{THANOS_EXTERNAL}/api/v1/query_range",
        params={
            "query": query,
            "start": SUMMIT_START,
            "end": SUMMIT_END,
            "step": step,
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if resp.status_code != 200:
        return {"error": resp.status_code, "body": resp.text[:200]}
    return resp.json()


def main():
    if not TOKEN:
        print("Set THANOS_TOKEN:")
        print("  export THANOS_TOKEN=$(oc create token deepfield-alertmanager -n deepfield --duration=1h)")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Mining Prometheus data for Summit week ({SUMMIT_START} to {SUMMIT_END})")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Queries: {len(QUERIES)}")
    print()

    results = {}
    with httpx.Client(timeout=30.0, verify=False) as client:
        for name, spec in QUERIES.items():
            print(f"  {name}...", end=" ", flush=True)
            try:
                data = query_range(client, spec["query"], spec["step"])
                status = data.get("status", "")
                result_data = data.get("data", {}).get("result", [])
                if status == "success" and result_data:
                    results[name] = {
                        "description": spec["description"],
                        "query": spec["query"],
                        "step": spec["step"],
                        "result": result_data,
                    }
                    total_points = sum(len(r.get("values", [])) for r in result_data)
                    print(f"{len(result_data)} series, {total_points} points")
                else:
                    print(f"empty ({data.get('error', status)})")
            except Exception as e:
                print(f"error: {e}")
            time.sleep(0.5)

    # Write individual metric files
    for name, data in results.items():
        outfile = OUTPUT_DIR / f"{name}.json"
        with open(outfile, "w") as f:
            json.dump(data, f, indent=2)

    # Write summary
    summary = {
        "mined_at": datetime.utcnow().isoformat() + "Z",
        "summit_start": SUMMIT_START,
        "summit_end": SUMMIT_END,
        "thanos_url": THANOS_EXTERNAL,
        "metrics_collected": list(results.keys()),
        "metrics_failed": [k for k in QUERIES if k not in results],
        "total_series": sum(len(d["result"]) for d in results.values()),
    }
    with open(OUTPUT_DIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{len(results)}/{len(QUERIES)} metrics collected")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
