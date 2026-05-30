"""Observatory API — full detail on agents, models, signals, clusters.

In-memory data first, falls back to PostgreSQL for history.
Supports `since` query parameter for time-windowed queries.
"""

from typing import Optional
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/observatory", tags=["observatory"])


def _get_store():
    from app.api.session import _get_current_session
    session = _get_current_session()
    if not session or not hasattr(session, 'store'):
        return None
    return session.store


def _filter_by_since(items: list, since: Optional[str], ts_field: str = "_ts") -> list:
    """Filter a list of dicts by timestamp, keeping items after `since`."""
    if not since or not items:
        return items
    from datetime import datetime, timezone
    try:
        cutoff = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return items
    result = []
    for item in items:
        ts = item.get(ts_field) or item.get("timestamp") or item.get("created_at")
        if not ts:
            result.append(item)
            continue
        try:
            if isinstance(ts, str):
                item_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                item_time = ts
            if item_time >= cutoff:
                result.append(item)
        except (ValueError, TypeError):
            result.append(item)
    return result


@router.get("/agents")
async def get_agents(since: Optional[str] = Query(None, description="ISO timestamp cutoff")):
    store = _get_store()
    if store and store.agent_stats:
        decisions = store.get_recent_decisions(200)
        filtered = _filter_by_since(decisions, since)
        if since and filtered != decisions:
            agent_counts: dict = {}
            for d in filtered:
                name = d.get("filter_name", "")
                if name not in agent_counts:
                    agent_counts[name] = {"total_evaluated": 0, "escalated": 0, "kept": 0, "dropped": 0, "suppressed": 0, "deduped": 0, "errors": 0}
                agent_counts[name]["total_evaluated"] += 1
                outcome = d.get("outcome", "")
                if outcome in agent_counts[name]:
                    agent_counts[name][outcome] += 1
            return {"agents": agent_counts, "recent_decisions": filtered[:50]}
        return {
            "agents": store.get_agent_summary(),
            "recent_decisions": filtered[:50],
        }
    from app import db
    if since:
        decisions = await db.query("SELECT * FROM decisions WHERE created_at >= $1 ORDER BY created_at DESC LIMIT 200", since)
    else:
        decisions = await db.query("SELECT * FROM decisions ORDER BY created_at DESC LIMIT 50")
    return {"agents": {}, "recent_decisions": decisions}


@router.get("/llm")
async def get_llm(since: Optional[str] = Query(None)):
    store = _get_store()
    if store and store.model_stats:
        inferences = store.get_recent_inferences(100)
        filtered = _filter_by_since(inferences, since)
        if since and filtered != inferences:
            model_counts: dict = {}
            for inf in filtered:
                model = inf.get("model", "unknown")
                if model not in model_counts:
                    model_counts[model] = {"total_calls": 0, "total_tokens_in": 0, "total_tokens_out": 0, "total_latency_ms": 0, "errors": 0, "task_types": {}}
                model_counts[model]["total_calls"] += 1
                model_counts[model]["total_tokens_in"] += inf.get("tokens_in", 0)
                model_counts[model]["total_tokens_out"] += inf.get("tokens_out", 0)
                model_counts[model]["total_latency_ms"] += inf.get("latency_ms", 0)
                tt = inf.get("task_type", "")
                model_counts[model]["task_types"][tt] = model_counts[model]["task_types"].get(tt, 0) + 1
            return {"models": model_counts, "recent_inferences": filtered[:30]}
        return {
            "models": store.get_model_summary(),
            "recent_inferences": filtered[:30],
        }
    from app import db
    if since:
        inferences = await db.query("SELECT * FROM inferences WHERE created_at >= $1 ORDER BY created_at DESC LIMIT 30", since)
    else:
        inferences = await db.query("SELECT * FROM inferences ORDER BY created_at DESC LIMIT 30")
    return {"models": {}, "recent_inferences": inferences}


@router.get("/signals")
async def get_signals(since: Optional[str] = Query(None)):
    store = _get_store()
    if store and store.recent_signals:
        signals = store.get_recent_signals(200)
        findings = store.get_recent_findings(50)
        return {
            "signals": _filter_by_since(signals, since),
            "findings": _filter_by_since(findings, since),
        }
    from app import db
    if since:
        signals = await db.query("SELECT * FROM signals WHERE created_at >= $1 ORDER BY created_at DESC LIMIT 200", since)
        findings = await db.query("SELECT * FROM findings WHERE created_at >= $1 ORDER BY created_at DESC LIMIT 50", since)
    else:
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
async def get_inference_history(limit: int = 100, since: Optional[str] = Query(None)):
    """Historical inferences from database — survives restarts."""
    from app import db
    if since:
        rows = await db.query("SELECT * FROM inferences WHERE created_at >= $1 ORDER BY created_at DESC LIMIT $2", since, limit)
    else:
        rows = await db.query("SELECT * FROM inferences ORDER BY created_at DESC LIMIT $1", limit)
    return {"inferences": rows, "source": "database"}


@router.get("/history/remediations")
async def get_remediation_history(limit: int = 50, since: Optional[str] = Query(None)):
    """Remediation audit trail from database."""
    from app import db
    if since:
        rows = await db.query("SELECT * FROM remediations WHERE created_at >= $1 ORDER BY created_at DESC LIMIT $2", since, limit)
    else:
        rows = await db.query("SELECT * FROM remediations ORDER BY created_at DESC LIMIT $1", limit)
    return {"remediations": rows, "source": "database"}
