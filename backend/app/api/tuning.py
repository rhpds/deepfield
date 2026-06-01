"""Tuning API — view and manage adaptive tuning proposals and cluster profiles."""

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/v1/tuning", tags=["tuning"])


@router.get("/proposals")
async def get_proposals(cluster_id: Optional[str] = None, status: str = "pending"):
    """Get tuning proposals, optionally filtered by cluster and status."""
    from app import db
    if cluster_id:
        rows = await db.query(
            "SELECT * FROM tuning_proposals WHERE cluster_id = $1 AND status = $2 ORDER BY created_at DESC",
            cluster_id, status,
        )
    else:
        rows = await db.query(
            "SELECT * FROM tuning_proposals WHERE status = $1 ORDER BY created_at DESC LIMIT 50",
            status,
        )
    return {"proposals": rows, "count": len(rows)}


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str):
    """Approve a tuning proposal — applies it to the cluster profile."""
    from app import db
    await db.execute(
        "UPDATE tuning_proposals SET status = 'approved', reviewed_at = NOW() WHERE proposal_id = $1",
        proposal_id,
    )
    return {"status": "approved", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    """Reject a tuning proposal."""
    from app import db
    await db.execute(
        "UPDATE tuning_proposals SET status = 'rejected', reviewed_at = NOW() WHERE proposal_id = $1",
        proposal_id,
    )
    return {"status": "rejected", "proposal_id": proposal_id}


@router.get("/profile/{cluster_id}")
async def get_profile(cluster_id: str):
    """Get the adaptive profile for a cluster."""
    from app.session.cluster_profile import get_profile as _get_profile
    profile = _get_profile(cluster_id)
    import json
    return json.loads(profile.to_json())
