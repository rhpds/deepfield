"""WebSocket endpoint for live session streaming."""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/session")
async def session_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            from app.api.session import _current_session_id
            from app.session.live_session import get_session

            if _current_session_id:
                session = get_session(_current_session_id)
                if session:
                    state = session.get_state()
                    await websocket.send_text(json.dumps(state, default=str))

            # Also send cluster metrics
            try:
                from app.api.runs import _get_prometheus
                prom = _get_prometheus()
                if prom:
                    metrics = prom.get_cluster_metrics()
                    await websocket.send_text(json.dumps({"type": "cluster_metrics", **metrics}, default=str))
            except Exception:
                pass

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
