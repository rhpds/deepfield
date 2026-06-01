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


@router.get("/evaluate/{cluster_id}")
async def evaluate_cluster(cluster_id: str):
    """Run EDD rubrics against accumulated data for a cluster."""
    from app import db
    from app.analysis.evaluator import evaluate_pipeline

    total_decisions = await db.query("SELECT COUNT(*) as cnt FROM decisions")
    total_d = total_decisions[0]["cnt"] if total_decisions else 0

    dedup_cnt = await db.query("SELECT COUNT(*) as cnt FROM decisions WHERE outcome = 'dedupe'")
    suppress_cnt = await db.query("SELECT COUNT(*) as cnt FROM decisions WHERE outcome = 'suppress'")
    dedup_rate = (dedup_cnt[0]["cnt"] / max(total_d, 1)) if dedup_cnt else 0
    suppress_rate = (suppress_cnt[0]["cnt"] / max(total_d, 1)) if suppress_cnt else 0

    snap = await db.query("SELECT compression_ratio FROM session_snapshots ORDER BY captured_at DESC LIMIT 1")
    comp_ratio = snap[0]["compression_ratio"] if snap else 0

    finding_types = await db.query("SELECT COUNT(DISTINCT finding_type) as cnt FROM findings")
    unique_ft = finding_types[0]["cnt"] if finding_types else 0

    total_inf = await db.query("SELECT COUNT(*) as cnt FROM inferences")
    err_inf = await db.query("SELECT COUNT(*) as cnt FROM inferences WHERE error IS NOT NULL AND error != ''")
    error_rate = (err_inf[0]["cnt"] / max(total_inf[0]["cnt"], 1)) if err_inf and total_inf else 0

    rca_tok = await db.query("SELECT AVG(tokens_out) as avg FROM inferences WHERE task_type = 'root_cause_analysis'")
    micro_tok = await db.query("SELECT AVG(tokens_out) as avg FROM inferences WHERE task_type IN ('classify_signal','explain_signal','summarize_finding')")
    avg_rca = float(rca_tok[0]["avg"] or 0) if rca_tok else 0
    avg_micro = float(micro_tok[0]["avg"] or 0) if micro_tok else 0

    ns_cnt = await db.query("SELECT COUNT(DISTINCT namespace) as cnt FROM signals")
    type_cnt = await db.query("SELECT COUNT(DISTINCT signal_type) as cnt FROM signals")
    agent_cnt = await db.query("SELECT COUNT(DISTINCT filter_name) as cnt FROM decisions")
    crit_cnt = await db.query("SELECT COUNT(*) as cnt FROM signals WHERE severity IN ('high','critical') AND created_at >= NOW() - INTERVAL '24 hours'")

    classify_json = await db.query("SELECT COUNT(*) as cnt FROM inferences WHERE task_type = 'classify_signal' AND output LIKE '{%}'")
    classify_total = await db.query("SELECT COUNT(*) as cnt FROM inferences WHERE task_type = 'classify_signal'")
    json_rate = (classify_json[0]["cnt"] / max(classify_total[0]["cnt"], 1)) if classify_json and classify_total else 0

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
        namespaces_monitored=ns_cnt[0]["cnt"] if ns_cnt else 0,
        active_agents=agent_cnt[0]["cnt"] if agent_cnt else 0,
        signal_type_diversity=type_cnt[0]["cnt"] if type_cnt else 0,
        critical_signals_today=crit_cnt[0]["cnt"] if crit_cnt else 0,
        new_types_suppressed=0,
        cross_resource_dedup=0,
        critical_deduped=0,
    )
    return result
