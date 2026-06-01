#!/usr/bin/env python3
"""Run the full E2E scenario suite and report results.

Usage:
    python -m app.testing.run_e2e                    # run all scenarios
    python -m app.testing.run_e2e pod_crashloop      # run one scenario
    python -m app.testing.run_e2e --list              # list available scenarios

Requires CLUSTER_1_API_URL and CLUSTER_1_TOKEN env vars for real pod injection.
Synthetic signal scenarios work without cluster access.
"""

import asyncio
import os
import sys
import time


def main():
    from app.testing.scenario_runner import ScenarioRunner, SCENARIOS

    if "--list" in sys.argv:
        for sid, s in SCENARIOS.items():
            print(f"  {sid:20s} {s.name:30s} ns={s.namespace:20s} → {s.expected_classification}")
        return

    target = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    scenarios_to_run = [target] if target else list(SCENARIOS.keys())

    cluster_url = os.environ.get("CLUSTER_1_API_URL", "")
    cluster_token = os.environ.get("CLUSTER_1_TOKEN", "")
    runner = ScenarioRunner(cluster_api_url=cluster_url, token=cluster_token)

    if not cluster_url:
        print("WARNING: CLUSTER_1_API_URL not set — real pod injection will be skipped")
        print("         Only synthetic_signal scenarios will fully work\n")

    results = []
    total_start = time.monotonic()

    for sid in scenarios_to_run:
        if sid not in SCENARIOS:
            print(f"Unknown scenario: {sid}")
            continue

        s = SCENARIOS[sid]
        print(f"{'='*60}")
        print(f"Running: {s.name}")
        print(f"  Namespace: {s.namespace}")
        print(f"  Inject: {s.inject_type}")
        print(f"  Expected: {s.expected_classification} ({s.expected_severity})")
        print(f"  Waiting for pipeline (up to 10 min)...")

        start = time.monotonic()
        result = asyncio.run(runner.run_scenario(sid))
        elapsed = time.monotonic() - start

        status = result.get("status", "?")
        checks = result.get("checks", [])
        passed = sum(1 for c in checks if c.get("passed"))

        icon = "PASS" if status == "pass" else "FAIL" if status == "fail" else status.upper()
        print(f"\n  [{icon}] {elapsed:.0f}s — {passed}/{len(checks)} checks passed")

        for c in checks:
            mark = "✓" if c.get("passed") else "✗"
            print(f"    {mark} {c['check']:25s} {c['detail']}")

        inc = result.get("incident")
        if inc:
            print(f"\n  Incident: {inc.get('namespace')} | {inc.get('failure_class', '-')} | {inc.get('signal_count', 0)} signals | {len(inc.get('remediation_options', []))} remediation options")

        if result.get("error"):
            print(f"\n  ERROR: {result['error']}")

        results.append(result)
        print()

    total_elapsed = time.monotonic() - total_start
    passed_count = sum(1 for r in results if r.get("status") == "pass")
    failed_count = sum(1 for r in results if r.get("status") == "fail")
    other_count = len(results) - passed_count - failed_count

    print(f"{'='*60}")
    print(f"E2E RESULTS: {passed_count} pass, {failed_count} fail, {other_count} other — {total_elapsed:.0f}s total")
    print(f"{'='*60}")

    sys.exit(0 if failed_count == 0 and other_count == 0 else 1)


if __name__ == "__main__":
    main()
