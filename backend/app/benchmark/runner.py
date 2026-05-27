"""Benchmark runner — concurrent execution with live progress tracking."""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
from uuid import uuid4

from app.inference.client import InferenceClient
from app.benchmark.generator import BenchmarkWorkloadGenerator
from app.benchmark.metrics import aggregate_benchmark_results, detect_saturation_point, BenchmarkMetrics
from app.domain.models import BenchmarkRequest


def _execute_request(client: InferenceClient, req: BenchmarkRequest, concurrency: int) -> dict:
    t0 = time.monotonic()
    resp = client.infer(
        model=req.model_preference,
        prompt=req.prompt,
        max_tokens=req.expected_output_tokens,
    )
    elapsed_ms = (time.monotonic() - t0) * 1000

    return {
        "request_id": str(req.request_id),
        "model_name": resp.model_name,
        "hardware_lane": resp.hardware_lane,
        "concurrency_level": concurrency,
        "status": resp.status,
        "latency_ms": resp.latency_ms if resp.status == "success" else elapsed_ms,
        "ttft_ms": resp.ttft_ms,
        "tokens_in": resp.tokens_in,
        "tokens_out": resp.tokens_out,
        "tokens_per_second": resp.tokens_per_second,
        "error": resp.error,
        "task_type": req.task_type,
    }


# Global registry for live progress polling
_active_runs: Dict[str, dict] = {}


def get_run_progress(run_id: str) -> Optional[dict]:
    return _active_runs.get(run_id)


def list_active_runs() -> List[str]:
    return list(_active_runs.keys())


class BenchmarkRunner:
    def __init__(self, client: InferenceClient, seed: int = 42):
        self.client = client
        self.seed = seed

    def run(self, profile: str, models: Optional[List[str]] = None, _run_id: Optional[str] = None) -> dict:
        gen = BenchmarkWorkloadGenerator(profile, seed=self.seed, models=models)
        bp = gen.profile
        run_id = _run_id or str(uuid4())

        from datetime import datetime, timezone
        total_requests = len(bp.models) * bp.requests_per_model * len(bp.concurrency_levels)
        now = datetime.now(timezone.utc).isoformat()
        if run_id in _active_runs:
            progress = _active_runs[run_id]
            progress["status"] = "running"
            progress["total"] = total_requests
            progress["started_at"] = now
        else:
            progress = {
                "run_id": run_id,
                "profile": profile,
                "status": "running",
                "total": total_requests,
                "completed": 0,
                "errors": 0,
                "current_concurrency": 0,
                "elapsed_ms": 0,
                "started_at": now,
                "completed_at": None,
                "results": [],
                "live_model_metrics": {},
                "metrics_timeline": [],
            }
            _active_runs[run_id] = progress

        all_results: list[dict] = []
        metrics_by_concurrency: dict[str, list[BenchmarkMetrics]] = {}

        start = time.monotonic()
        metrics_stop = threading.Event()
        metrics_thread = self._start_metrics_capture(progress, start, metrics_stop)

        try:
            for concurrency in bp.concurrency_levels:
                progress["current_concurrency"] = concurrency
                requests = gen.generate(benchmark_run_id=uuid4())
                level_start = time.monotonic()
                level_results = []

                num_models = len(set(r.model_preference for r in requests))
                workers = max(1, concurrency * max(1, num_models))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(_execute_request, self.client, req, concurrency): req
                        for req in requests
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        result["benchmark_run_id"] = run_id
                        level_results.append(result)
                        all_results.append(result)

                        progress["completed"] = len(all_results)
                        progress["elapsed_ms"] = round((time.monotonic() - start) * 1000, 2)
                        if result.get("error"):
                            progress["errors"] += 1

                        model = result["model_name"]
                        if model not in progress["live_model_metrics"]:
                            progress["live_model_metrics"][model] = {
                                "hardware_lane": result["hardware_lane"],
                                "completed": 0, "errors": 0,
                                "total_latency": 0, "total_tokens_out": 0,
                                "total_tps": 0, "count_tps": 0,
                            }
                        lm = progress["live_model_metrics"][model]
                        lm["completed"] += 1
                        if result["status"] != "success":
                            lm["errors"] += 1
                        else:
                            lm["total_latency"] += result["latency_ms"]
                            lm["total_tokens_out"] += result["tokens_out"]
                            lm["total_tps"] += result["tokens_per_second"]
                            lm["count_tps"] += 1
                        ok = lm["completed"] - lm["errors"]
                        lm["avg_latency_ms"] = round(lm["total_latency"] / ok, 1) if ok else 0
                        lm["avg_tps"] = round(lm["total_tps"] / lm["count_tps"], 1) if lm["count_tps"] else 0

                level_duration = (time.monotonic() - level_start) * 1000
                level_metrics = aggregate_benchmark_results(level_results, concurrency, level_duration)
                for m in level_metrics:
                    metrics_by_concurrency.setdefault(m.model_name, []).append(m)

        finally:
            metrics_stop.set()
            total_duration_ms = (time.monotonic() - start) * 1000
            progress["status"] = "done"
            progress["elapsed_ms"] = round(total_duration_ms, 2)
            progress["completed_at"] = datetime.now(timezone.utc).isoformat()

        saturation = {}
        for model, concurrency_metrics in metrics_by_concurrency.items():
            saturation[model] = detect_saturation_point(concurrency_metrics)

        overall_metrics = aggregate_benchmark_results(all_results, total_duration_ms=total_duration_ms)

        final = {
            "benchmark_run_id": run_id,
            "profile": profile,
            "total_requests": len(all_results),
            "duration_ms": round(total_duration_ms, 2),
            "concurrency_levels": bp.concurrency_levels,
            "results": all_results,
            "model_metrics": {m.model_name: vars(m) for m in overall_metrics},
            "saturation": saturation,
            "metrics_by_concurrency": {
                model: [vars(m) for m in mlist] for model, mlist in metrics_by_concurrency.items()
            },
        }
        progress["final"] = final
        return final

    def _start_metrics_capture(self, progress: dict, start_time: float, stop_event: threading.Event):
        def _capture():
            try:
                from app.inference.prometheus import PrometheusPoller
                poller = PrometheusPoller()
            except Exception:
                return
            while not stop_event.is_set():
                stop_event.wait(2.0)
                if stop_event.is_set():
                    break
                try:
                    metrics = poller.get_cluster_metrics()
                    elapsed = round((time.monotonic() - start_time) * 1000, 2)
                    snapshot = {
                        "t_ms": elapsed,
                        "completed": progress.get("completed", 0),
                        "concurrency": progress.get("current_concurrency", 0),
                        "models": metrics.get("models", {}),
                    }
                    progress.setdefault("metrics_timeline", []).append(snapshot)
                except Exception:
                    pass
            poller.stop()

        t = threading.Thread(target=_capture, daemon=True)
        t.start()
        return t

    def run_background(self, profile: str, models: Optional[List[str]] = None) -> str:
        gen = BenchmarkWorkloadGenerator(profile, seed=self.seed, models=models)
        run_id = str(uuid4())
        total_requests = len(gen.profile.models) * gen.profile.requests_per_model * len(gen.profile.concurrency_levels)
        _active_runs[run_id] = {
            "run_id": run_id, "profile": profile, "status": "starting",
            "total": total_requests, "completed": 0, "errors": 0,
            "current_concurrency": 0, "elapsed_ms": 0, "live_model_metrics": {},
        }

        def _worker():
            try:
                result = self.run(profile, models, _run_id=run_id)
                _active_runs[run_id]["final"] = result
                _active_runs[run_id]["status"] = "done"
            except Exception as e:
                _active_runs[run_id]["status"] = "error"
                _active_runs[run_id]["error"] = str(e)

        # Override the run_id in the thread
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return run_id

    def run_model_comparison(self, models: Optional[List[str]] = None) -> dict:
        return self.run("model_race", models=models)
