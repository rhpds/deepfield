"""Unified metrics endpoint — single query for all dashboard data, windowed by time range."""

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1", tags=["metrics"])

WINDOW_INTERVALS = {
    "5m": "5 minutes",
    "15m": "15 minutes",
    "1h": "1 hour",
    "6h": "6 hours",
    "24h": "24 hours",
    "7d": "7 days",
}


def _get_store():
    from app.api.session import _get_current_session
    session = _get_current_session()
    if not session or not hasattr(session, 'store'):
        return None, None
    return session, session.store


@router.get("/metrics")
async def get_metrics(window: str = Query("1h", description="Time window: 5m, 15m, 1h, 6h, 24h, 7d")):
    interval = WINDOW_INTERVALS.get(window, "1 hour")
    session, store = _get_store()

    from app import db

    agents: dict = {}
    agent_decisions = await db.query(
        f"SELECT filter_name, outcome, COUNT(*) as cnt FROM decisions "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"GROUP BY filter_name, outcome"
    )
    for row in agent_decisions:
        name = row["filter_name"]
        if name not in agents:
            agents[name] = {"total_evaluated": 0, "escalated": 0, "kept": 0, "dropped": 0, "suppressed": 0, "deduped": 0}
        agents[name]["total_evaluated"] += row["cnt"]
        outcome = row["outcome"]
        if outcome in agents[name]:
            agents[name][outcome] += row["cnt"]

    if not agents and store:
        agents = store.get_agent_summary()

    signals_by_sev = await db.query(
        f"SELECT severity, COUNT(*) as cnt FROM signals "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"GROUP BY severity"
    )
    signal_summary = {"total": 0, "by_severity": {}}
    for row in signals_by_sev:
        signal_summary["by_severity"][row["severity"]] = row["cnt"]
        signal_summary["total"] += row["cnt"]

    models: dict = {}
    model_rows = await db.query(
        f"SELECT model, COUNT(*) as calls, "
        f"AVG(latency_ms) as avg_latency, "
        f"SUM(tokens_out) as total_tokens_out, "
        f"SUM(tokens_in) as total_tokens_in "
        f"FROM inferences "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"GROUP BY model"
    )
    for row in model_rows:
        total_time = (row["avg_latency"] or 0) * (row["calls"] or 1) / 1000
        models[row["model"]] = {
            "total_calls": row["calls"],
            "avg_latency": round(row["avg_latency"] or 0, 1),
            "avg_tps": round((row["total_tokens_out"] or 0) / max(total_time, 0.1), 1),
            "total_tokens_in": row["total_tokens_in"] or 0,
            "total_tokens_out": row["total_tokens_out"] or 0,
        }

    sig_count = await db.query(
        f"SELECT COUNT(*) as cnt FROM signals WHERE created_at >= NOW() - INTERVAL '{interval}'"
    )
    finding_count = await db.query(
        f"SELECT COUNT(*) as cnt FROM findings WHERE created_at >= NOW() - INTERVAL '{interval}'"
    )
    inf_count = await db.query(
        f"SELECT COUNT(*) as cnt FROM inferences WHERE created_at >= NOW() - INTERVAL '{interval}'"
    )
    decision_count = await db.query(
        f"SELECT COUNT(*) as cnt FROM decisions WHERE created_at >= NOW() - INTERVAL '{interval}'"
    )
    dedup_count = await db.query(
        f"SELECT COUNT(*) as cnt FROM decisions WHERE outcome = 'dedupe' AND created_at >= NOW() - INTERVAL '{interval}'"
    )

    raw = decision_count[0]["cnt"] if decision_count else 0
    deduped = dedup_count[0]["cnt"] if dedup_count else 0
    funnel = {
        "raw": raw,
        "retained": sig_count[0]["cnt"] if sig_count else 0,
        "findings": finding_count[0]["cnt"] if finding_count else 0,
        "tasks": raw - deduped,
        "inferences": inf_count[0]["cnt"] if inf_count else 0,
    }

    # Fall back to in-memory when DB has no data for this window
    if raw == 0 and session and hasattr(session, 'totals'):
        t = session.totals
        funnel = {
            "raw": t.get("raw_signals", 0),
            "retained": t.get("retained", 0),
            "findings": t.get("findings", 0),
            "tasks": t.get("reasoning_tasks", 0),
            "inferences": t.get("inference_calls", 0),
        }

    live_metrics = session.metrics if session else {}

    recent_signals = await db.query(
        f"SELECT * FROM signals WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"ORDER BY created_at DESC LIMIT 20"
    )
    if not recent_signals and store:
        recent_signals = store.get_recent_signals(20)

    recent_decisions = await db.query(
        f"SELECT * FROM decisions WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"ORDER BY created_at DESC LIMIT 30"
    )
    if not recent_decisions and store:
        recent_decisions = store.get_recent_decisions(30)

    recent_inferences = await db.query(
        f"SELECT * FROM inferences WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"ORDER BY created_at DESC LIMIT 20"
    )
    if not recent_inferences and store:
        recent_inferences = store.get_recent_inferences(20)

    window_seconds = {"5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}.get(window, 3600)
    raw_total = funnel.get("raw", 0)
    windowed_sps = round(raw_total / max(window_seconds, 1), 1) if raw_total > 0 else live_metrics.get("signals_per_second", 0)
    retained_total = funnel.get("retained", 0)
    tasks_total = funnel.get("tasks", 0)
    windowed_cr = round(raw_total / max(tasks_total, 1), 1) if tasks_total > 0 else live_metrics.get("compression_ratio", 0)

    return {
        "window": window,
        "agents": agents,
        "signals": signal_summary,
        "models": models,
        "funnel": funnel,
        "compression_ratio": windowed_cr,
        "signals_per_second": windowed_sps,
        "inference_in_flight": live_metrics.get("inference_in_flight", 0),
        "recent_signals": recent_signals,
        "recent_decisions": recent_decisions,
        "recent_inferences": recent_inferences,
    }
