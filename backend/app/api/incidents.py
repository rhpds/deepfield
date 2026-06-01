"""Incidents API — rich evidence-driven incidents with append semantics."""

from typing import Optional
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        from app.session.incident_manager import IncidentManager
        _manager = IncidentManager()
    return _manager


def get_manager():
    """Public accessor for the process loop to use."""
    return _get_manager()


@router.get("")
async def list_incidents(status: Optional[str] = Query(None), window: Optional[str] = Query(None)):
    mgr = _get_manager()
    incidents = mgr.list_incidents(status=status)
    if window:
        from datetime import datetime, timezone, timedelta
        windows = {"5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440, "7d": 10080}
        minutes = windows.get(window, 60)
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        incidents = [i for i in incidents if i.get("last_seen", "") >= cutoff]
    return {"incidents": incidents, "count": len(incidents)}


@router.get("/{incident_id}")
async def get_incident(incident_id: str):
    mgr = _get_manager()
    inc = mgr.get_incident(incident_id)
    if not inc:
        return {"error": "not found"}
    return inc


@router.post("/{incident_id}/resolve")
async def resolve_incident(incident_id: str):
    mgr = _get_manager()
    return mgr.resolve_incident(incident_id)


@router.post("/{incident_id}/suppress")
async def suppress_incident(incident_id: str):
    mgr = _get_manager()
    inc = mgr.get_incident(incident_id)
    if inc:
        inc["status"] = "suppressed"
        return inc
    return {"error": "not found"}
