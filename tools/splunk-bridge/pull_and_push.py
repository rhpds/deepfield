#!/usr/bin/env python3
"""Splunk → DeepField bridge. Pulls recent errors from Splunk, pushes as signals.

Runs locally on VPN. Hourly via launchd.
    python3 tools/splunk-bridge/pull_and_push.py

Reads .env for Splunk credentials. Pushes to DeepField webhook.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("splunk-bridge")

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)

SPLUNK_URL = os.getenv("SPLUNK_URL", "https://splunk-api.corp.redhat.com:8089")
DEEPFIELD_URL = os.getenv("DEEPFIELD_URL", "")
if not DEEPFIELD_URL:
    logger.error("Set DEEPFIELD_URL to your DeepField endpoint")
    sys.exit(1)

ENV_FILE = Path(__file__).parent.parent.parent / ".env"

CHECKPOINT_FILE = Path(__file__).parent / ".last_run"
MAX_LOOKBACK_HOURS = 24


def get_lookback() -> str:
    """Return Splunk earliest time. Uses checkpoint to backfill missed runs."""
    if CHECKPOINT_FILE.exists():
        try:
            last = float(CHECKPOINT_FILE.read_text().strip())
            hours_ago = (time.time() - last) / 3600
            if hours_ago > MAX_LOOKBACK_HOURS:
                hours_ago = MAX_LOOKBACK_HOURS
            return f"-{int(hours_ago) + 1}h"
        except (ValueError, OSError):
            pass
    return "-1h"


def save_checkpoint():
    try:
        CHECKPOINT_FILE.write_text(str(time.time()))
    except OSError:
        pass


SEVERITY_MAP = {
    "ERROR": "high",
    "FATAL": "critical",
    "WARN": "medium",
    "WARNING": "medium",
}

QUERIES = [
    {
        "name": "ocp_app_errors",
        "index": "federated:rh_pds-001_ocp_app",
        "spl": 'level=ERROR | stats count by kubernetes.namespace_name, kubernetes.container_name | where count > 10 | sort -count | head 25',
        "signal_type": "splunk_error_spike",
    },
    {
        "name": "ocp_app_crashloops",
        "index": "federated:rh_pds-001_ocp_app",
        "spl": '(CrashLoopBackOff OR OOMKilled OR "exit code 137" OR panic) | stats count by kubernetes.namespace_name | where count > 3 | sort -count | head 15',
        "signal_type": "splunk_critical_alert",
    },
    {
        "name": "aap_errors",
        "index": "federated:rh_pds-001_aap",
        "spl": 'level=ERROR | stats count by cluster_host_id, logger_name | where count > 5 | sort -count | head 10',
        "signal_type": "splunk_high_alert",
    },
    {
        "name": "ocp_infra_errors",
        "index": "federated:rh_pds-001_ocp_infra",
        "spl": 'level=error OR level=ERROR | stats count by kubernetes.container_name | where count > 50 | sort -count | head 10',
        "signal_type": "splunk_medium_alert",
    },
]


def load_credentials() -> tuple:
    username = os.getenv("SPLUNK_1_USERNAME", "")
    password = os.getenv("SPLUNK_1_PASSWORD", "")
    if not username and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("SPLUNK_1_USERNAME="):
                username = line.split("=", 1)[1]
            elif line.startswith("SPLUNK_1_PASSWORD="):
                password = line.split("=", 1)[1]
    return username, password


def run_search(client: httpx.Client, auth: tuple, index: str, spl: str) -> list:
    lookback = get_lookback()
    search = f'search index="{index}" earliest={lookback} latest=now {spl}'
    resp = client.post(
        f"{SPLUNK_URL}/services/search/jobs",
        auth=auth,
        data={"search": search, "output_mode": "json", "exec_mode": "oneshot", "max_count": "100"},
    )
    if resp.status_code != 200:
        logger.warning("Splunk query failed: %d", resp.status_code)
        return []
    return resp.json().get("results", [])


def push_to_deepfield(client: httpx.Client, signals: list) -> int:
    pushed = 0
    for sig in signals:
        try:
            resp = client.post(
                f"{DEEPFIELD_URL}/integration/splunk",
                json=sig,
                timeout=10.0,
            )
            if resp.status_code == 200:
                pushed += 1
            else:
                logger.warning("DeepField push failed: %d", resp.status_code)
        except Exception as e:
            logger.warning("DeepField push error: %s", str(e)[:80])
    return pushed


def main():
    username, password = load_credentials()
    if not username or not password:
        logger.error("Set SPLUNK_1_USERNAME and SPLUNK_1_PASSWORD in .env")
        sys.exit(1)

    # Test Splunk connectivity
    try:
        with httpx.Client(timeout=15.0, verify=False) as client:
            resp = client.get(f"{SPLUNK_URL}/services/server/info",
                              auth=(username, password), params={"output_mode": "json"})
            if resp.status_code != 200:
                logger.error("Splunk auth failed (%d). On VPN?", resp.status_code)
                sys.exit(1)
    except Exception as e:
        logger.error("Can't reach Splunk: %s. On VPN?", e)
        sys.exit(1)

    logger.info("Pulling last 1h from Splunk (%d queries)...", len(QUERIES))

    all_signals = []
    with httpx.Client(timeout=120.0, verify=False) as client:
        for q in QUERIES:
            results = run_search(client, (username, password), q["index"], q["spl"])
            if not results:
                continue

            for r in results:
                ns = r.get("kubernetes.namespace_name", r.get("cluster_host_id", "unknown"))
                resource = r.get("kubernetes.container_name", r.get("logger_name", q["name"]))
                count = int(r.get("count", "1"))

                sig = {
                    "search_name": q["name"],
                    "app": ns,
                    "severity": "4" if q["signal_type"] == "splunk_critical_alert" else "3",
                    "result": {
                        "namespace": ns,
                        "resource": resource,
                        "count": count,
                        "query": q["name"],
                        "source_index": q["index"],
                    },
                }
                all_signals.append(sig)

            logger.info("  %s: %d results", q["name"], len(results))
            time.sleep(1)

    if not all_signals:
        logger.info("No signals to push")
        return

    # Push to DeepField
    logger.info("Pushing %d signals to DeepField...", len(all_signals))
    with httpx.Client(verify=False) as client:
        pushed = push_to_deepfield(client, all_signals)

    logger.info("Done: %d/%d signals pushed", pushed, len(all_signals))
    save_checkpoint()


if __name__ == "__main__":
    main()
