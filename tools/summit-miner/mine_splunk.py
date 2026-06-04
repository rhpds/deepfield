#!/usr/bin/env python3
"""Mine Splunk data from Summit week (May 5-8, 2026).

REQUIRES VPN — run from a corp-connected machine:
    python3 tools/summit-miner/mine_splunk.py

Uses credentials from .env (SPLUNK_1_USERNAME, SPLUNK_1_PASSWORD).
Outputs JSON files to data/summit-2026/splunk/
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

SPLUNK_URL = "https://splunk-api.corp.redhat.com:8089"
ENV_FILE = Path(__file__).parent.parent.parent / ".env"

SUMMIT_START = "2026-05-05T00:00:00"
SUMMIT_END = "2026-05-08T23:59:59"

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "summit-2026" / "splunk"

QUERIES = {
    "ocp_app_errors": {
        "index": "federated:rh_pds-001_ocp_app",
        "spl": 'level=ERROR | stats count by kubernetes.namespace_name, level | sort -count | head 50',
        "description": "Top 50 error-producing namespaces from OCP application logs",
    },
    "ocp_app_error_messages": {
        "index": "federated:rh_pds-001_ocp_app",
        "spl": 'level=ERROR | rex field=_raw "\"message\":\"(?<error_msg>[^\"]{1,300})\"" | stats count by kubernetes.namespace_name, error_msg | sort -count | head 100',
        "description": "Top 100 error messages by namespace",
    },
    "ocp_app_warn_rate": {
        "index": "federated:rh_pds-001_ocp_app",
        "spl": '(level=ERROR OR level=WARN OR level=FATAL) | timechart span=1h count by level',
        "description": "Hourly error/warn/fatal rate over Summit week",
    },
    "ocp_infra_errors": {
        "index": "federated:rh_pds-001_ocp_infra",
        "spl": 'level=error OR level=ERROR | stats count by kubernetes.container_name | sort -count | head 30',
        "description": "Top 30 error-producing infrastructure components",
    },
    "ocp_infra_kubelet": {
        "index": "federated:rh_pds-001_ocp_infra",
        "spl": 'kubernetes.container_name=kubelet level=error | stats count by hostname | sort -count | head 20',
        "description": "Kubelet errors by node",
    },
    "ocp_audit_denied": {
        "index": "federated:rh_pds-001_ocp_audit",
        "spl": '"authorization.k8s.io/decision"="forbid" | stats count by objectRef.resource, objectRef.namespace | sort -count | head 30',
        "description": "Top 30 RBAC denials by resource and namespace",
    },
    "ocp_audit_high_volume_users": {
        "index": "federated:rh_pds-001_ocp_audit",
        "spl": '| stats count by user.username | sort -count | head 20',
        "description": "Top 20 API users by request volume",
    },
    "aap_job_failures": {
        "index": "federated:rh_pds-001_aap",
        "spl": 'level=ERROR | stats count by cluster_host_id, logger_name | sort -count | head 30',
        "description": "AAP errors by controller and logger",
    },
    "aap_error_timeline": {
        "index": "federated:rh_pds-001_aap",
        "spl": '(level=ERROR OR level=WARNING) | timechart span=1h count by level',
        "description": "Hourly AAP error/warning rate",
    },
    "ocp_app_crashloop_logs": {
        "index": "federated:rh_pds-001_ocp_app",
        "spl": '(CrashLoopBackOff OR OOMKilled OR "exit code" OR "fatal error" OR panic) | stats count by kubernetes.namespace_name | sort -count | head 30',
        "description": "Namespaces with crash/OOM/panic in logs",
    },
}


def load_credentials() -> tuple:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("SPLUNK_1_USERNAME="):
                username = line.split("=", 1)[1]
            elif line.startswith("SPLUNK_1_PASSWORD="):
                password = line.split("=", 1)[1]
        return username, password
    return os.getenv("SPLUNK_1_USERNAME", ""), os.getenv("SPLUNK_1_PASSWORD", "")


def run_search(client: httpx.Client, auth: tuple, index: str, spl: str) -> list:
    search = f'search index="{index}" earliest="{SUMMIT_START}" latest="{SUMMIT_END}" {spl}'
    resp = client.post(
        f"{SPLUNK_URL}/services/search/jobs",
        auth=auth,
        data={"search": search, "output_mode": "json", "exec_mode": "oneshot", "max_count": "500"},
    )
    if resp.status_code != 200:
        return [{"error": resp.status_code, "body": resp.text[:300]}]
    data = resp.json()
    return data.get("results", [])


def main():
    username, password = load_credentials()
    if not username or not password:
        print("Set SPLUNK_1_USERNAME and SPLUNK_1_PASSWORD in .env")
        sys.exit(1)

    # Test connectivity
    print(f"Testing Splunk API at {SPLUNK_URL}...")
    try:
        with httpx.Client(timeout=15.0, verify=False) as client:
            resp = client.get(
                f"{SPLUNK_URL}/services/server/info",
                auth=(username, password),
                params={"output_mode": "json"},
            )
            if resp.status_code != 200:
                print(f"Auth failed: {resp.status_code}. Are you on VPN?")
                sys.exit(1)
    except Exception as e:
        print(f"Cannot reach Splunk API: {e}")
        print("Make sure you're connected to Red Hat VPN.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Mining Splunk data for Summit week ({SUMMIT_START} to {SUMMIT_END})")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Queries: {len(QUERIES)}")
    print()

    results = {}
    with httpx.Client(timeout=120.0, verify=False) as client:
        for name, spec in QUERIES.items():
            print(f"  {name}...", end=" ", flush=True)
            try:
                data = run_search(client, (username, password), spec["index"], spec["spl"])
                if data and not (len(data) == 1 and "error" in data[0]):
                    results[name] = {
                        "description": spec["description"],
                        "index": spec["index"],
                        "spl": spec["spl"],
                        "result_count": len(data),
                        "results": data,
                    }
                    print(f"{len(data)} results")
                else:
                    error = data[0].get("error", "empty") if data else "empty"
                    print(f"empty/error ({error})")
            except Exception as e:
                print(f"error: {e}")
            time.sleep(2)

    for name, data in results.items():
        outfile = OUTPUT_DIR / f"{name}.json"
        with open(outfile, "w") as f:
            json.dump(data, f, indent=2)

    summary = {
        "mined_at": datetime.utcnow().isoformat() + "Z",
        "summit_start": SUMMIT_START,
        "summit_end": SUMMIT_END,
        "splunk_url": SPLUNK_URL,
        "queries_collected": list(results.keys()),
        "queries_failed": [k for k in QUERIES if k not in results],
        "total_results": sum(d["result_count"] for d in results.values()),
    }
    with open(OUTPUT_DIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{len(results)}/{len(QUERIES)} queries collected")
    print(f"Total results: {summary['total_results']}")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
