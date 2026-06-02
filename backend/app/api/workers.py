"""API for Kafka worker consumer stats and replay management."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends

from app.auth import require_write_access

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


@router.get("")
async def get_worker_stats():
    from app.workers.manager import get_worker_manager
    mgr = get_worker_manager()
    if not mgr:
        return {"workers": [], "total_processed": 0, "total_errors": 0, "status": "not_started"}
    stats = mgr.stats()
    stats["status"] = "running"
    stats["replays"] = mgr.list_replays()
    return stats


@router.post("/replay", dependencies=[Depends(require_write_access)])
async def start_replay(body: dict):
    """Start a Kafka replay with a separate consumer group."""
    from app.workers.manager import get_worker_manager
    mgr = get_worker_manager()
    if not mgr:
        return {"error": "Workers not started"}

    from_ts = body.get("from_timestamp")
    to_ts = body.get("to_timestamp")

    if isinstance(from_ts, str):
        from_ts = int(datetime.fromisoformat(from_ts.replace("Z", "+00:00")).timestamp() * 1000)
    if isinstance(to_ts, str):
        to_ts = int(datetime.fromisoformat(to_ts.replace("Z", "+00:00")).timestamp() * 1000)

    if not from_ts or not to_ts:
        return {"error": "from_timestamp and to_timestamp required"}

    replay_id = mgr.start_replay(from_timestamp_ms=from_ts, to_timestamp_ms=to_ts)
    return {"replay_id": replay_id, "status": "started"}


@router.get("/replay/{replay_id}")
async def get_replay_status(replay_id: str):
    from app.workers.manager import get_worker_manager
    mgr = get_worker_manager()
    if not mgr:
        return {"error": "Workers not started"}
    result = mgr.get_replay(replay_id)
    if not result:
        return {"error": "Replay not found"}
    return result


@router.post("/replay/{replay_id}/stop", dependencies=[Depends(require_write_access)])
async def stop_replay(replay_id: str):
    from app.workers.manager import get_worker_manager
    mgr = get_worker_manager()
    if not mgr:
        return {"error": "Workers not started"}
    mgr.stop_replay(replay_id)
    return {"status": "stopped", "replay_id": replay_id}
