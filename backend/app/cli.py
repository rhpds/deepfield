"""DeepField CLI."""

import json
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: deepfield <command> [options]")
        print("Commands: run-synthetic, benchmark, capacity-report, scan-live")
        sys.exit(1)

    command = sys.argv[1]

    if command == "run-synthetic":
        _run_synthetic()
    elif command == "benchmark":
        _run_benchmark()
    elif command == "capacity-report":
        _capacity_report()
    elif command == "scan-live":
        _scan_live()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


def _parse_args(args):
    parsed = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:].replace("-", "_")
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                parsed[key] = args[i + 1]
                i += 2
            else:
                parsed[key] = True
                i += 1
        else:
            i += 1
    return parsed


def _run_synthetic():
    from app.orchestrator import run_synthetic
    args = _parse_args(sys.argv[2:])
    profile = args.get("profile", "tiny")
    seed = int(args.get("seed", 42))
    result = run_synthetic(profile=profile, seed=seed)
    print(result["report_md"])
    print(f"\nRun ID: {result['run_id']}")
    print(f"Compression Ratio: {result['funnel']['reasoning_compression_ratio']:,.1f}:1")


def _run_benchmark():
    from app.orchestrator import run_benchmark
    args = _parse_args(sys.argv[2:])
    profile = args.get("profile", "model_race")
    seed = int(args.get("seed", 42))
    mode = args.get("mode", "mock")
    result = run_benchmark(profile=profile, seed=seed, mode=mode)
    print(result["report_md"])
    print(f"\nBenchmark Run ID: {result['benchmark_run_id']}")


def _capacity_report():
    from app.orchestrator import run_synthetic, run_benchmark, run_capacity_projection
    args = _parse_args(sys.argv[2:])
    seed = int(args.get("seed", 42))
    profile = args.get("profile", "small")

    print("Running synthetic fleet...")
    synthetic = run_synthetic(profile=profile, seed=seed)
    print(f"  Signals: {synthetic['raw_signals']}, Tasks: {synthetic['reasoning_tasks']}")

    print("Running benchmark...")
    benchmark = run_benchmark(profile="model_race", seed=seed, mode="mock")
    print(f"  Requests: {benchmark['total_requests']}")

    print("\nComputing capacity projection...")
    projection = run_capacity_projection(synthetic, benchmark)
    print(f"\n{'='*60}")
    print(f"DEEPFIELD CAPACITY PROJECTION")
    print(f"{'='*60}")
    print(f"Reasoning Compression Ratio: {projection['compression_ratio']:,.1f}:1")
    print(f"Max Reasoning Tasks/min:     {projection['max_reasoning_tasks_per_minute']:,.1f}")
    print(f"Avg Signals/Cluster:         {projection['avg_signals_per_cluster']:,.0f}")
    print(f"p95 Latency:                 {projection['p95_latency_ms']:,.0f}ms")
    print(f"")
    print(f">>> PROJECTED CLUSTERS SUPPORTED: {projection['projected_clusters_supported']}")
    print(f"{'='*60}")


def _scan_live():
    print("Live fleet scanning is a stub in MVP.")
    print("The OpenShift collector interface exists but requires:")
    print("  --config configs/live/clusters.yaml")
    print("  --read-only (enforced)")
    print("No cluster mutation will be performed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
