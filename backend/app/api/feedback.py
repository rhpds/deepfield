"""Feedback API — human evaluation of LLM outputs on incidents."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.auth import require_write_access
from app.db import enqueue_write

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


class FeedbackSubmission(BaseModel):
    incident_id: str
    target_type: str = Field(..., pattern=r"^(rca|inference|remediation)$")
    target_index: int = 0
    rating: str = Field(..., pattern=r"^(up|down)$")
    comment: str = ""
    model: str = ""
    task_type: str = ""


@router.post("", dependencies=[Depends(require_write_access)])
async def submit_feedback(body: FeedbackSubmission, request: Request):
    user_id = request.headers.get("X-Forwarded-User", "")
    enqueue_write("feedback", {
        "incident_id": body.incident_id,
        "target_type": body.target_type,
        "target_index": body.target_index,
        "rating": body.rating,
        "comment": body.comment,
        "model": body.model,
        "task_type": body.task_type,
        "user_id": user_id,
    })
    return {"status": "ok"}


@router.get("")
async def list_feedback(
    incident_id: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    from app import db

    if incident_id:
        rows = await db.query(
            "SELECT * FROM feedback WHERE incident_id = $1 ORDER BY created_at DESC LIMIT $2",
            incident_id, limit,
        )
    elif target_type:
        rows = await db.query(
            "SELECT * FROM feedback WHERE target_type = $1 ORDER BY created_at DESC LIMIT $2",
            target_type, limit,
        )
    else:
        rows = await db.query(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT $1", limit,
        )
    return {"feedback": rows, "count": len(rows)}


@router.get("/summary")
async def feedback_summary(window: Optional[str] = Query(None)):
    from app import db

    WINDOW_SQL = {
        "1h": "1 hour", "6h": "6 hours", "24h": "24 hours",
        "7d": "7 days", "30d": "30 days",
    }
    interval = WINDOW_SQL.get(window or "7d", "7 days")

    by_model = await db.query(
        "SELECT model, rating, COUNT(*) as cnt FROM feedback "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' AND model != '' "
        "GROUP BY model, rating ORDER BY model"
    )

    by_task = await db.query(
        "SELECT task_type, rating, COUNT(*) as cnt FROM feedback "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' AND task_type != '' "
        "GROUP BY task_type, rating ORDER BY task_type"
    )

    by_target = await db.query(
        "SELECT target_type, rating, COUNT(*) as cnt FROM feedback "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
        "GROUP BY target_type, rating ORDER BY target_type"
    )

    negative_with_comments = await db.query(
        "SELECT incident_id, target_type, target_index, model, task_type, comment, created_at "
        "FROM feedback "
        f"WHERE rating = 'down' AND comment != '' AND created_at >= NOW() - INTERVAL '{interval}' "
        "ORDER BY created_at DESC LIMIT 20"
    )

    def _pivot(rows, key_field):
        result = {}
        for r in rows:
            k = r[key_field]
            if k not in result:
                result[k] = {"up": 0, "down": 0, "total": 0}
            result[k][r["rating"]] += r["cnt"]
            result[k]["total"] += r["cnt"]
        for v in result.values():
            v["approval_rate"] = round(v["up"] / max(v["total"], 1), 3)
        return result

    return {
        "window": window or "7d",
        "by_model": _pivot(by_model, "model") if by_model else {},
        "by_task_type": _pivot(by_task, "task_type") if by_task else {},
        "by_target_type": _pivot(by_target, "target_type") if by_target else {},
        "negative_comments": negative_with_comments,
    }
