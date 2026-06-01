"""Observatory API — signal, agent, model, and cluster data.

Supports ?window= query param (5m, 15m, 1h, 6h, 24h, 7d) for time-filtered views.
Falls back to in-memory session data when DB is empty.
"""

from typing import Optional
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/observatory", tags=["observatory"])

WINDOW_SQL = {
    "5m": "5 minutes", "15m": "15 minutes", "1h": "1 hour",
    "6h": "6 hours", "24h": "24 hours", "7d": "7 days",
}


def _get_store():
    from app.api.session import _get_current_session
    session = _get_current_session()
    if not session or not hasattr(session, 'store'):
        return None
    return session.store


def _interval(window: Optional[str]) -> str:
    return WINDOW_SQL.get(window or "1h", "1 hour")


@router.get("/agents")
async def get_agents(window: Optional[str] = Query(None)):
    from app import db
    interval = _interval(window)

    if window:
        rows = await db.query(
            f"SELECT filter_name, outcome, COUNT(*) as cnt FROM decisions "
            f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
            f"GROUP BY filter_name, outcome ORDER BY filter_name"
        )
        outcome_map = {"escalate": "escalated", "suppress": "suppressed", "dedupe": "deduped",
                       "keep": "kept", "drop": "dropped", "enrich": "enriched"}
        agents: dict = {}
        for r in rows:
            name = r["filter_name"]
            if name not in agents:
                agents[name] = {"total_evaluated": 0, "escalated": 0, "kept": 0, "dropped": 0, "suppressed": 0, "deduped": 0, "enriched": 0}
            agents[name]["total_evaluated"] += r["cnt"]
            mapped = outcome_map.get(r["outcome"], r["outcome"])
            if mapped in agents[name]:
                agents[name][mapped] += r["cnt"]

        # Add agents that exist in pipeline but have no DB decisions
        ALL_AGENTS = [
            "FailureClassifierAgent", "EventClassifierAgent", "PodHealthAgent",
            "RouteHealthAgent", "PVCHealthAgent", "NodePressureAgent",
            "NamespaceQuotaAgent", "KServeEndpointAgent", "KafkaLagAgent",
            "LaunchpadSessionAgent", "StarGateEvaluationAgent",
            "TransientSuppressorAgent", "DedupeAgent",
        ]
        for agent_name in ALL_AGENTS:
            if agent_name not in agents:
                agents[agent_name] = {"total_evaluated": 0, "escalated": 0, "kept": 0, "dropped": 0, "suppressed": 0, "deduped": 0, "enriched": 0}

        # Estimate kept count from in-memory ratio (keep decisions not persisted to DB)
        store = _get_store()
        if store and store.agent_stats:
            for name, db_stats in agents.items():
                mem = store.agent_stats.get(name)
                if mem and mem.total_evaluated > 0:
                    keep_ratio = mem.kept / mem.total_evaluated
                    db_actionable = db_stats["total_evaluated"]
                    estimated_total = int(db_actionable / max(1 - keep_ratio, 0.01))
                    db_stats["kept"] = estimated_total - db_actionable
                    db_stats["total_evaluated"] = estimated_total

        decisions = await db.query(
            f"SELECT * FROM decisions WHERE created_at >= NOW() - INTERVAL '{interval}' "
            f"ORDER BY created_at DESC LIMIT 50"
        )
        if agents:
            return {"agents": agents, "recent_decisions": decisions}

    store = _get_store()
    if store and store.agent_stats:
        return {
            "agents": store.get_agent_summary(),
            "recent_decisions": store.get_recent_decisions(50),
        }
    decisions = await db.query("SELECT * FROM decisions ORDER BY created_at DESC LIMIT 50")
    return {"agents": {}, "recent_decisions": decisions}


@router.get("/llm")
async def get_llm(window: Optional[str] = Query(None)):
    from app import db
    interval = _interval(window)

    if window:
        inferences = await db.query(
            f"SELECT * FROM inferences WHERE created_at >= NOW() - INTERVAL '{interval}' "
            f"ORDER BY created_at DESC LIMIT 50"
        )
        models: dict = {}
        for inf in inferences:
            m = inf.get("model", "unknown")
            if m not in models:
                models[m] = {"total_calls": 0, "total_tokens_in": 0, "total_tokens_out": 0, "total_latency_ms": 0, "errors": 0, "task_types": {}}
            models[m]["total_calls"] += 1
            models[m]["total_tokens_out"] += inf.get("tokens_out", 0) or 0
            models[m]["total_latency_ms"] += inf.get("latency_ms", 0) or 0
            tt = inf.get("task_type", "")
            models[m]["task_types"][tt] = models[m]["task_types"].get(tt, 0) + 1
        if models:
            return {"models": models, "recent_inferences": inferences[:30]}

    store = _get_store()
    if store and store.model_stats:
        return {
            "models": store.get_model_summary(),
            "recent_inferences": store.get_recent_inferences(30),
        }
    inferences = await db.query("SELECT * FROM inferences ORDER BY created_at DESC LIMIT 30")
    return {"models": {}, "recent_inferences": inferences}


@router.get("/signals")
async def get_signals(window: Optional[str] = Query(None)):
    from app import db
    interval = _interval(window)

    if window:
        signals = await db.query(
            f"SELECT * FROM signals WHERE created_at >= NOW() - INTERVAL '{interval}' "
            f"ORDER BY created_at DESC LIMIT 200"
        )
        findings = await db.query(
            f"SELECT * FROM findings WHERE created_at >= NOW() - INTERVAL '{interval}' "
            f"ORDER BY created_at DESC LIMIT 50"
        )
        return {"signals": signals, "findings": findings, "total": len(signals)}

    store = _get_store()
    if store and store.recent_signals:
        return {
            "signals": store.get_recent_signals(50),
            "findings": store.get_recent_findings(20),
        }
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
async def get_inference_history(limit: int = 100, window: Optional[str] = Query(None)):
    from app import db
    if window:
        interval = _interval(window)
        rows = await db.query(
            f"SELECT * FROM inferences WHERE created_at >= NOW() - INTERVAL '{interval}' "
            f"ORDER BY created_at DESC LIMIT $1", limit
        )
    else:
        rows = await db.query("SELECT * FROM inferences ORDER BY created_at DESC LIMIT $1", limit)
    return {"inferences": rows, "source": "database"}


@router.get("/history/remediations")
async def get_remediation_history(limit: int = 50, window: Optional[str] = Query(None)):
    from app import db
    if window:
        interval = _interval(window)
        rows = await db.query(
            f"SELECT * FROM remediations WHERE created_at >= NOW() - INTERVAL '{interval}' "
            f"ORDER BY created_at DESC LIMIT $1", limit
        )
    else:
        rows = await db.query("SELECT * FROM remediations ORDER BY created_at DESC LIMIT $1", limit)
    return {"remediations": rows, "source": "database"}
