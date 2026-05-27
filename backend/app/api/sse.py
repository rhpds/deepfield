"""Server-Sent Events endpoint for live streaming."""

import asyncio
import json

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

router = APIRouter()


@router.get("/api/v1/stream")
async def session_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            # Cluster metrics (Prometheus)
            try:
                from app.api.runs import _get_prometheus
                prom = _get_prometheus()
                if prom:
                    metrics = prom.get_cluster_metrics()
                    yield f"event: cluster\ndata: {json.dumps(metrics, default=str)}\n\n"
            except Exception:
                pass

            # Live monitoring session (always running)
            try:
                from app.api.session import get_live_session
                live = get_live_session()
                if live:
                    state = live.get_state()
                    yield f"event: live\ndata: {json.dumps(state, default=str)}\n\n"
            except Exception:
                pass

            # Synthetic session (Demo / Simulator — push-button)
            try:
                from app.api.session import _get_synthetic
                synth = _get_synthetic()
                if synth:
                    state = synth.get_state()
                    yield f"event: session\ndata: {json.dumps(state, default=str)}\n\n"
            except Exception:
                pass

            # Demo state
            try:
                from app.api.demo import _demo_state
                if _demo_state and _demo_state.get("status") in ("running", "completed"):
                    safe = {k: v for k, v in _demo_state.items() if k != "steps"}
                    safe["step_count"] = len(_demo_state.get("steps", []))
                    if _demo_state.get("current_step", 0) < len(_demo_state.get("steps", [])):
                        safe["current_step_info"] = _demo_state["steps"][_demo_state["current_step"]]
                    yield f"event: demo\ndata: {json.dumps(safe, default=str)}\n\n"
            except Exception:
                pass

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
