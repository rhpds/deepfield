"""API for Kafka worker consumer stats."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


@router.get("")
async def get_worker_stats():
    from app.workers.manager import get_worker_manager
    mgr = get_worker_manager()
    if not mgr:
        return {"workers": [], "total_processed": 0, "total_errors": 0, "status": "not_started"}
    stats = mgr.stats()
    stats["status"] = "running"
    return stats
