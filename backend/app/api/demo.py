"""Auto-demo orchestration — guided story arc."""

import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_write_access

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

_demo_state: dict = {}
_demo_thread: Optional[threading.Thread] = None
_demo_stop = threading.Event()

DEMO_STEPS = [
    {
        "id": "hardware",
        "title": "Intel Hardware Power",
        "subtitle": "Measuring raw Gaudi 3 inference throughput",
        "description": "Running a quick benchmark across all Gaudi 3 model endpoints to establish baseline throughput — tokens/sec, RPS, and latency per model.",
        "action": "benchmark",
        "duration": 15,
        "params": {},
    },
    {
        "id": "baseline",
        "title": "Fleet Baseline",
        "subtitle": "5 clusters, 1% failure rate — minimal load",
        "description": "Starting signal stream from 5 synthetic OpenShift clusters at 1% failure rate. Watch the nano-agent filters compress the telemetry. Most signals are healthy noise — only a tiny fraction requires LLM reasoning.",
        "action": "stream",
        "duration": 20,
        "params": {"clusters": 5, "failure_rate": 0.01, "signals_per_second": 100},
    },
    {
        "id": "scale",
        "title": "Scale Up",
        "subtitle": "Scaling to 50 clusters — 10x fleet size",
        "description": "Scaling the fleet from 5 to 50 clusters. Signal volume increases 10x but the compression ratio holds — deterministic filters scale linearly. Watch the projected clusters number climb.",
        "action": "update",
        "duration": 20,
        "params": {"clusters": 50, "signals_per_second": 500},
    },
    {
        "id": "stress",
        "title": "Stress Test",
        "subtitle": "Cranking failure rate to 15% — simulating incident storm",
        "description": "Injecting 15% failure rate across the fleet — simulating a cascade of pod crashes, route failures, and node pressure. Watch compression ratio drop, reasoning tasks spike, and the pressure gauges climb as the inference cluster takes on real load.",
        "action": "update",
        "duration": 25,
        "params": {"failure_rate": 0.15},
    },
    {
        "id": "recovery",
        "title": "Recovery",
        "subtitle": "Failure rate back to 2% — fleet stabilizing",
        "description": "Incident resolved. Failure rate drops back to 2%. Watch the compression ratio recover, reasoning tasks drop, pressure gauges return to green. The system self-stabilizes without intervention.",
        "action": "update",
        "duration": 20,
        "params": {"failure_rate": 0.02},
    },
    {
        "id": "claim",
        "title": "The Claim",
        "subtitle": "One inference cluster can monitor N OpenShift clusters",
        "description": "Final measurement. Using deterministic nano-agent filters, DeepField compressed fleet telemetry so only a fraction required expensive reasoning. Combined with measured Gaudi 3 throughput, we can project how many clusters one Intel inference cluster can monitor.",
        "action": "receipt",
        "duration": 10,
        "params": {},
    },
]


class DemoStartRequest(BaseModel):
    mode: str = "real"
    seed: int = 42


@router.post("/start", dependencies=[Depends(require_write_access)])
async def start_demo(req: DemoStartRequest):
    global _demo_thread
    _demo_stop.clear()
    _demo_state.clear()
    _demo_state.update({
        "status": "running",
        "current_step": 0,
        "steps": DEMO_STEPS,
        "step_progress": 0,
        "mode": req.mode,
        "seed": req.seed,
    })

    def _run():
        import httpx
        client = httpx.Client(timeout=30, verify=False)
        base = "http://localhost:8099"

        for i, step in enumerate(DEMO_STEPS):
            if _demo_stop.is_set():
                break

            _demo_state["current_step"] = i
            _demo_state["step_progress"] = 0

            if step["action"] == "benchmark":
                # Quick benchmark
                try:
                    resp = client.post(f"{base}/api/v1/runs/benchmark", json={
                        "profile": "gaudi_blast", "seed": req.seed, "mode": req.mode, "background": True,
                    })
                    data = resp.json()
                    _demo_state["benchmark_run_id"] = data.get("run_id")
                except Exception:
                    pass

            elif step["action"] == "stream":
                # Start streaming session
                try:
                    client.post(f"{base}/api/v1/session/start", json={
                        "mode": req.mode, "seed": req.seed, "routing_mode": "demo", **step["params"],
                    })
                except Exception:
                    pass

            elif step["action"] == "update":
                # Update params
                try:
                    client.post(f"{base}/api/v1/session/update", json=step["params"])
                except Exception:
                    pass

            elif step["action"] == "receipt":
                # Get final live state then stop
                try:
                    state_resp = client.get(f"{base}/api/v1/session/state")
                    live_state = state_resp.json()
                    resp = client.post(f"{base}/api/v1/session/stop")
                    data = resp.json()
                    receipt = data.get("receipt", {})
                    # Use live projected clusters if higher than snapshot peak
                    live_projected = live_state.get("metrics", {}).get("projected_clusters", 0)
                    if live_projected > receipt.get("peak_projected_clusters", 0):
                        receipt["peak_projected_clusters"] = live_projected
                    live_comp = live_state.get("metrics", {}).get("compression_ratio", 0)
                    if live_comp > receipt.get("max_compression_ratio", 0):
                        receipt["max_compression_ratio"] = live_comp
                    _demo_state["receipt"] = receipt
                except Exception:
                    pass

            # Wait for step duration with progress updates
            step_start = time.monotonic()
            while not _demo_stop.is_set():
                elapsed = time.monotonic() - step_start
                _demo_state["step_progress"] = min(100, int((elapsed / step["duration"]) * 100))
                if elapsed >= step["duration"]:
                    break
                time.sleep(0.5)

        _demo_state["status"] = "completed"
        _demo_state["current_step"] = len(DEMO_STEPS) - 1
        client.close()

    _demo_thread = threading.Thread(target=_run, daemon=True)
    _demo_thread.start()
    return {"status": "started", "steps": len(DEMO_STEPS)}


@router.post("/stop", dependencies=[Depends(require_write_access)])
async def stop_demo():
    _demo_stop.set()
    # Also stop any running session
    try:
        import httpx
        httpx.Client(timeout=5, verify=False).post("http://localhost:8099/api/v1/session/stop")
    except Exception:
        pass
    _demo_state["status"] = "stopped"
    return {"status": "stopped"}


@router.get("/state")
async def get_demo_state():
    return _demo_state if _demo_state else {"status": "idle"}
