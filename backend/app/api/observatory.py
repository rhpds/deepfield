"""Observatory API — current session data for real-time views.

Returns in-memory data from the active session. For time-windowed
historical queries, use /api/v1/metrics?window= instead.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/observatory", tags=["observatory"])


def _get_store():
    from app.api.session import _get_current_session
    session = _get_current_session()
    if not session or not hasattr(session, 'store'):
        return None
    return session.store


@router.get("/agents")
async def get_agents():
    store = _get_store()
    if store and store.agent_stats:
        return {
            "agents": store.get_agent_summary(),
            "recent_decisions": store.get_recent_decisions(50),
        }
    from app import db
    decisions = await db.query("SELECT * FROM decisions ORDER BY created_at DESC LIMIT 50")
    return {"agents": {}, "recent_decisions": decisions}


@router.get("/llm")
async def get_llm():
    store = _get_store()
    if store and store.model_stats:
        return {
            "models": store.get_model_summary(),
            "recent_inferences": store.get_recent_inferences(30),
        }
    from app import db
    inferences = await db.query("SELECT * FROM inferences ORDER BY created_at DESC LIMIT 30")
    return {"models": {}, "recent_inferences": inferences}


@router.get("/signals")
async def get_signals():
    store = _get_store()
    if store and store.recent_signals:
        return {
            "signals": store.get_recent_signals(50),
            "findings": store.get_recent_findings(20),
        }
    from app import db
    signals = await db.query("SELECT * FROM signals ORDER BY created_at DESC LIMIT 50")
    findings = await db.query("SELECT * FROM findings ORDER BY created_at DESC LIMIT 20")
    return {"signals": signals, "findings": findings}


@router.get("/clusters")
async def get_clusters():
    store = _get_store()
    if not store:
        return {"clusters": {}}
    return {"clusters": store.get_cluster_summary()}


@router.get("/history/inferences")
async def get_inference_history(limit: int = 100):
    """Historical inferences from database — survives restarts."""
    from app import db
    rows = await db.query("SELECT * FROM inferences ORDER BY created_at DESC LIMIT $1", limit)
    return {"inferences": rows, "source": "database"}


@router.get("/history/remediations")
async def get_remediation_history(limit: int = 50):
    """Remediation audit trail from database."""
    from app import db
    rows = await db.query("SELECT * FROM remediations ORDER BY created_at DESC LIMIT $1", limit)
    return {"remediations": rows, "source": "database"}
