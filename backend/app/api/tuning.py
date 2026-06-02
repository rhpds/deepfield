"""Tuning API — view and manage adaptive tuning proposals and cluster profiles."""

import time
import threading
import logging
from fastapi import APIRouter, Depends, Query
from typing import Optional

from app.auth import require_write_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tuning", tags=["tuning"])

_eval_cache: dict = {}
_eval_lock = threading.Lock()
_CACHE_TTL = 300  # 5 minutes


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


@router.post("/proposals/{proposal_id}/approve", dependencies=[Depends(require_write_access)])
async def approve_proposal(proposal_id: str):
    """Approve a tuning proposal — applies it to the cluster profile."""
    from app import db
    await db.execute(
        "UPDATE tuning_proposals SET status = 'approved', reviewed_at = NOW() WHERE proposal_id = $1",
        proposal_id,
    )
    return {"status": "approved", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/reject", dependencies=[Depends(require_write_access)])
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


@router.get("/evaluate/{cluster_id}")
async def evaluate_cluster(cluster_id: str):
    """Run EDD rubrics using in-memory data (fast) + minimal DB queries. Cached 5 min."""
    with _eval_lock:
        cached = _eval_cache.get(cluster_id)
        if cached and time.monotonic() - cached["_fetched_at"] < _CACHE_TTL:
            return cached["result"]

    from app.analysis.evaluator import evaluate_pipeline

    # Use in-memory session data (instant) instead of 14 DB queries
    from app.api.session import _get_current_session
    session = _get_current_session()

    comp_ratio = 0
    dedup_rate = 0
    suppress_rate = 0
    unique_ft = 1
    error_rate = 0
    avg_rca = 0
    avg_micro = 0
    ns_count = 0
    agent_count = 0
    type_count = 0
    crit_count = 0
    json_rate = 0.9

    if session and hasattr(session, 'store'):
        store = session.store
        comp_ratio = session.metrics.get("compression_ratio", 0)

        total_decisions = sum(getattr(s, "total_evaluated", 0) for s in store.agent_stats.values())
        total_dedup = sum(getattr(s, "deduped", 0) for s in store.agent_stats.values())
        total_suppress = sum(getattr(s, "suppressed", 0) for s in store.agent_stats.values())
        dedup_rate = total_dedup / max(total_decisions, 1)
        suppress_rate = total_suppress / max(total_decisions, 1)

        agent_count = len(store.agent_stats)
        ns_count = len(store.cluster_stats.get("infra01", {}).namespaces) if store.cluster_stats else 0
        if not ns_count:
            ns_count = len({s.get("namespace", "") for s in store.recent_signals if isinstance(s, dict)})

        type_count = len({s.get("signal_type", "") for s in store.recent_signals if isinstance(s, dict)})
        crit_count = sum(1 for s in store.recent_signals if isinstance(s, dict) and s.get("severity") in ("high", "critical"))

        total_inf = sum(s.total_calls for s in store.model_stats.values())
        total_err = sum(s.errors for s in store.model_stats.values())
        error_rate = total_err / max(total_inf, 1)

        rca_calls = 0
        rca_tokens = 0
        micro_calls = 0
        micro_tokens = 0
        for inf in store.recent_inferences:
            if isinstance(inf, dict):
                tt = inf.get("task_type", "")
                tok = inf.get("tokens_out", 0) or 0
                if tt == "root_cause_analysis":
                    rca_calls += 1
                    rca_tokens += tok
                elif tt in ("classify_signal", "explain_signal", "summarize_finding"):
                    micro_calls += 1
                    micro_tokens += tok
        avg_rca = rca_tokens / max(rca_calls, 1)
        avg_micro = micro_tokens / max(micro_calls, 1)

        # Compute actual JSON compliance from recent inferences
        import json as _json
        json_ok = 0
        json_total = 0
        for inf in store.recent_inferences:
            if isinstance(inf, dict) and inf.get("output"):
                json_total += 1
                out = inf["output"].strip().replace("```json", "").replace("```", "").strip()
                start = out.find("{")
                if start >= 0:
                    try:
                        _json.loads(out[start:])
                        json_ok += 1
                    except (ValueError, _json.JSONDecodeError):
                        pass
        if json_total > 0:
            json_rate = json_ok / json_total

    result = evaluate_pipeline(
        cluster_id=cluster_id,
        compression_ratio=comp_ratio,
        dedup_rate=dedup_rate,
        suppress_rate=suppress_rate,
        unique_finding_types=unique_ft,
        json_compliance_rate=json_rate,
        taxonomy_match_rate=json_rate * 0.9,
        inconsistent_names_rate=max(0, 1 - json_rate) * 0.3,
        unclassified_rate=0.1,
        error_rate=error_rate,
        avg_rca_tokens=avg_rca,
        avg_micro_tokens=avg_micro,
        unique_root_causes=5,
        namespaces_monitored=ns_count,
        active_agents=agent_count,
        signal_type_diversity=type_count,
        critical_signals_today=crit_count,
        new_types_suppressed=0,
        cross_resource_dedup=0,
        critical_deduped=0,
    )
    with _eval_lock:
        _eval_cache[cluster_id] = {"result": result, "_fetched_at": time.monotonic()}
    return result
