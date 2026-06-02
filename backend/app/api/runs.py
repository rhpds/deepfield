"""DeepField run API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.auth import require_write_access

from app.orchestrator import run_synthetic, run_benchmark, run_capacity_projection
from app.inference.client import MockInferenceClient
from app.benchmark.runner import get_run_progress, list_active_runs

router = APIRouter(prefix="/api/v1", tags=["runs"])

_runs: dict = {}
_benchmarks: dict = {}
_prometheus = None


@router.post("/preflight", dependencies=[Depends(require_write_access)])
async def preflight_check():
    import asyncio
    from app.benchmark.preflight import run_preflight
    return await asyncio.get_event_loop().run_in_executor(None, run_preflight)


@router.post("/warmup", dependencies=[Depends(require_write_access)])
async def warmup():
    import asyncio
    from app.benchmark.preflight import run_warmup
    return await asyncio.get_event_loop().run_in_executor(None, run_warmup)


def _get_prometheus():
    global _prometheus
    if _prometheus is None:
        try:
            from app.inference.prometheus import PrometheusPoller
            _prometheus = PrometheusPoller()
        except Exception:
            pass
    return _prometheus


def _get_client(mode: str, seed: int = 42):
    if mode == "real":
        from app.inference.adapters import RealInferenceClient
        return RealInferenceClient()
    return MockInferenceClient(seed=seed)


class SyntheticRunRequest(BaseModel):
    profile: str = "tiny"
    seed: int = 42
    mode: str = "mock"


class BenchmarkRunRequest(BaseModel):
    profile: str = "model_race"
    seed: int = 42
    mode: str = "mock"
    background: bool = False


class CapacityRequest(BaseModel):
    synthetic_profile: str = "small"
    benchmark_profile: str = "model_race"
    seed: int = 42
    mode: str = "mock"


@router.post("/runs/synthetic", dependencies=[Depends(require_write_access)])
async def start_synthetic_run(req: SyntheticRunRequest):
    import asyncio
    client = _get_client(req.mode, req.seed)
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: run_synthetic(profile=req.profile, seed=req.seed, inference_client=client)
    )
    _runs[result["run_id"]] = result
    return result


@router.post("/runs/benchmark", dependencies=[Depends(require_write_access)])
async def start_benchmark_run(req: BenchmarkRunRequest):
    client = _get_client(req.mode, req.seed)
    if req.background or req.mode == "real":
        from app.benchmark.runner import BenchmarkRunner
        runner = BenchmarkRunner(client, seed=req.seed)
        run_id = runner.run_background(req.profile)
        return {"run_id": run_id, "status": "started", "profile": req.profile, "mode": req.mode}
    result = run_benchmark(profile=req.profile, seed=req.seed, mode=req.mode, inference_client=client)
    _benchmarks[result["benchmark_run_id"]] = result
    return result


@router.get("/runs/benchmark/status/{run_id}")
async def get_benchmark_progress(run_id: str):
    progress = get_run_progress(run_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Run not found")
    return progress


@router.get("/runs/benchmark/active")
async def get_active_benchmarks():
    active = []
    for rid in list_active_runs():
        p = get_run_progress(rid)
        if p:
            active.append({
                "run_id": rid,
                "profile": p.get("profile"),
                "status": p.get("status"),
                "completed": p.get("completed", 0),
                "total": p.get("total", 0),
                "errors": p.get("errors", 0),
                "elapsed_ms": p.get("elapsed_ms", 0),
            })
    return {"active": active}


_capacity_runs: dict = {}


@router.post("/runs/capacity", dependencies=[Depends(require_write_access)])
async def start_capacity_run(req: CapacityRequest):
    import threading
    from uuid import uuid4
    run_id = str(uuid4())
    _capacity_runs[run_id] = {
        "run_id": run_id,
        "status": "running",
        "phase": "starting",
        "synthetic": None,
        "benchmark_run_id": None,
        "projection": None,
    }

    def _worker():
        try:
            # Synthetic always uses mock — we only care about compression ratio
            mock_client = MockInferenceClient(seed=req.seed)
            real_client = _get_client(req.mode, req.seed)
            _capacity_runs[run_id]["phase"] = "synthetic"
            synthetic = run_synthetic(profile=req.synthetic_profile, seed=req.seed, inference_client=mock_client)
            _capacity_runs[run_id]["synthetic"] = synthetic
            _runs[synthetic["run_id"]] = synthetic

            _capacity_runs[run_id]["phase"] = "benchmark"
            from app.benchmark.runner import BenchmarkRunner
            runner = BenchmarkRunner(real_client, seed=req.seed)
            bench_run_id = runner.run_background(req.benchmark_profile)
            _capacity_runs[run_id]["benchmark_run_id"] = bench_run_id

            from app.benchmark.runner import get_run_progress
            import time
            while True:
                time.sleep(1)
                progress = get_run_progress(bench_run_id)
                if not progress:
                    break
                _capacity_runs[run_id]["benchmark_progress"] = {
                    "completed": progress.get("completed", 0),
                    "total": progress.get("total", 0),
                    "live_model_metrics": progress.get("live_model_metrics", {}),
                }
                if progress.get("status") in ("done", "error"):
                    break

            progress = get_run_progress(bench_run_id)
            benchmark = progress.get("final", {}) if progress else {}
            benchmark["mode"] = req.mode
            _benchmarks[bench_run_id] = benchmark

            _capacity_runs[run_id]["phase"] = "projection"
            projection = run_capacity_projection(synthetic, benchmark)
            _capacity_runs[run_id]["projection"] = projection
            _capacity_runs[run_id]["benchmark"] = benchmark
            _capacity_runs[run_id]["status"] = "done"
            _capacity_runs[run_id]["phase"] = "done"
        except Exception as e:
            _capacity_runs[run_id]["status"] = "error"
            _capacity_runs[run_id]["error"] = str(e)

    threading.Thread(target=_worker, daemon=True).start()
    return {"run_id": run_id, "status": "started"}


@router.get("/runs/capacity/status/{run_id}")
async def get_capacity_progress(run_id: str):
    if run_id not in _capacity_runs:
        raise HTTPException(status_code=404, detail="Capacity run not found")
    cap = _capacity_runs[run_id]
    result = {
        "run_id": run_id,
        "status": cap["status"],
        "phase": cap.get("phase", "unknown"),
    }
    if cap.get("synthetic"):
        syn = {k: v for k, v in cap["synthetic"].items() if k not in ("report_json", "report_md")}
        result["synthetic"] = syn
    if cap.get("benchmark_run_id"):
        from app.benchmark.runner import get_run_progress
        bp = get_run_progress(cap["benchmark_run_id"])
        if bp:
            result["benchmark_progress"] = {
                "completed": bp.get("completed", 0),
                "total": bp.get("total", 0),
                "errors": bp.get("errors", 0),
                "elapsed_ms": bp.get("elapsed_ms", 0),
                "live_model_metrics": bp.get("live_model_metrics", {}),
                "metrics_timeline": bp.get("metrics_timeline", []),
            }
    if cap.get("projection"):
        result["projection"] = cap["projection"]
    if cap.get("benchmark"):
        bench = {k: v for k, v in cap["benchmark"].items() if k not in ("report_json", "report_md", "results")}
        result["benchmark"] = bench
    if cap.get("error"):
        result["error"] = cap["error"]
    return result


@router.get("/cluster/metrics")
async def get_cluster_metrics():
    prom = _get_prometheus()
    if not prom:
        return {"available": False, "models": {}, "nodes": {}}
    return prom.get_cluster_metrics()


@router.get("/runs")
async def list_runs():
    return {"runs": list(_runs.values()), "benchmarks": list(_benchmarks.values())}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    if run_id in _runs:
        return _runs[run_id]
    if run_id in _benchmarks:
        return _benchmarks[run_id]
    raise HTTPException(status_code=404, detail="Run not found")
