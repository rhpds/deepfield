"""Integration events router — receives webhook events from Launchpad and StarGate."""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_write_access

from app.domain.models import RawSignal
from app.generators.signal_types import SIGNAL_RESOURCE_KIND

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integration", tags=["integration"])

INTEGRATION_API_KEY = os.environ.get("INTEGRATION_API_KEY")

_seen_events: OrderedDict = OrderedDict()
_MAX_SEEN = 10000


def _verify_api_key(request: Request):
    if not INTEGRATION_API_KEY:
        return
    key = request.headers.get("X-API-Key")
    if key != INTEGRATION_API_KEY:
        raise HTTPException(401, "Invalid or missing X-API-Key")


def _check_duplicate(event_id: str) -> bool:
    if event_id in _seen_events:
        return True
    _seen_events[event_id] = True
    if len(_seen_events) > _MAX_SEEN:
        _seen_events.popitem(last=False)
    return False


class IntegrationEvent(BaseModel):
    source: Literal["launchpad", "stargate", "deepfield"]
    event_type: str
    event_id: str
    timestamp: str
    payload: dict


def _convert_launchpad_event(event: IntegrationEvent) -> RawSignal | None:
    payload = event.payload
    outcome = payload.get("outcome", "info")
    signal_type_map = {
        "pass": "launchpad_lab_active",
        "fail": "launchpad_lab_failed",
        "info": "launchpad_lab_active",
    }
    signal_type = signal_type_map.get(outcome, "launchpad_lab_active")

    try:
        ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)

    return RawSignal(
        signal_id=uuid4(),
        cluster_id=uuid4(),
        namespace=payload.get("cluster_name", "unknown"),
        resource_kind=SIGNAL_RESOURCE_KIND.get(signal_type, "LaunchpadSession"),
        resource_name=payload.get("session_id", "unknown"),
        source="launchpad",
        signal_type=signal_type,
        raw_payload=payload,
        timestamp=ts,
    )


def _convert_stargate_event(event: IntegrationEvent) -> RawSignal | None:
    payload = event.payload
    outcome = payload.get("outcome", "PASS")
    if outcome in ("FAIL", "fail"):
        signal_type = "stargate_stage_failed"
    elif outcome in ("PASS", "pass"):
        signal_type = "stargate_stage_passed"
    else:
        signal_type = "stargate_run_completed"

    try:
        ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)

    return RawSignal(
        signal_id=uuid4(),
        cluster_id=uuid4(),
        namespace=payload.get("namespace", "unknown"),
        resource_kind=SIGNAL_RESOURCE_KIND.get(signal_type, "StarGateRun"),
        resource_name=payload.get("run_id", payload.get("stage_id", "unknown")),
        source="stargate",
        signal_type=signal_type,
        raw_payload=payload,
        timestamp=ts,
    )


@router.post("/events", dependencies=[Depends(require_write_access)])
async def receive_event(event: IntegrationEvent, request: Request):
    """Receive integration events from Launchpad or StarGate."""
    _verify_api_key(request)

    if _check_duplicate(event.event_id):
        return {"received": True, "event_id": event.event_id, "duplicate": True}

    signal = None
    if event.source == "launchpad":
        signal = _convert_launchpad_event(event)
    elif event.source == "stargate":
        signal = _convert_stargate_event(event)
    else:
        return {"received": True, "processed": False, "reason": "unknown source"}

    if signal:
        from app.session.streaming_session import get_active_sessions
        sessions = get_active_sessions()
        injected = False
        for session in sessions.values():
            if hasattr(session, "_signal_queue"):
                session._signal_queue.append(signal)
                injected = True
        logger.info(
            "Received %s event: type=%s, injected=%s",
            event.source, event.event_type, injected,
        )

    return {"received": True, "event_id": event.event_id, "processed": True}
