"""Session API — separate live monitoring (auto-start) and synthetic (push-button)."""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_write_access
from app.session.streaming_session import create_streaming_session, get_streaming_session
from app.session.synthetic_session import create_synthetic_session, get_synthetic_session

router = APIRouter(prefix="/api/v1/session", tags=["session"])

_live_session_id: Optional[str] = None
_synthetic_session_id: Optional[str] = None

def _load_cluster_configs() -> list:
    """Load cluster configs from environment variables."""
    import json
    configs_json = os.getenv("CLUSTER_CONFIGS", "")
    if configs_json:
        try:
            return json.loads(configs_json)
        except json.JSONDecodeError:
            pass
    configs = []
    for i in range(1, 20):
        name = os.getenv(f"CLUSTER_{i}_NAME", "")
        api_url = os.getenv(f"CLUSTER_{i}_API_URL", "")
        token = os.getenv(f"CLUSTER_{i}_TOKEN", "")
        if name and api_url:
            configs.append({
                "name": name,
                "api_url": api_url,
                "token": token,
                "include_namespaces": os.getenv(f"CLUSTER_{i}_INCLUDE_NS", "*").split(","),
                "exclude_namespaces": os.getenv(f"CLUSTER_{i}_EXCLUDE_NS", "openshift-*,kube-*").split(","),
            })
    return configs


CLUSTER_CONFIGS = _load_cluster_configs()


def _load_splunk_configs() -> list:
    """Load Splunk instance configs from environment variables."""
    configs = []
    for i in range(1, 6):
        name = os.getenv(f"SPLUNK_{i}_NAME", "")
        url = os.getenv(f"SPLUNK_{i}_URL", "")
        token = os.getenv(f"SPLUNK_{i}_TOKEN", "")
        if name and url:
            configs.append({
                "name": name,
                "url": url,
                "token": token,
                "username": os.getenv(f"SPLUNK_{i}_USERNAME", ""),
                "password": os.getenv(f"SPLUNK_{i}_PASSWORD", ""),
                "poll_interval": int(os.getenv(f"SPLUNK_{i}_POLL_INTERVAL", "60")),
                "indexes": os.getenv(f"SPLUNK_{i}_INDEXES", "*").split(","),
            })
    return configs


SPLUNK_CONFIGS = _load_splunk_configs()


def start_live_monitoring():
    """Auto-start live monitoring at pod startup. Uses real inference."""
    global _live_session_id
    try:
        from app.inference.adapters import RealInferenceClient
        client = RealInferenceClient()
    except Exception:
        from app.inference.client import MockInferenceClient
        client = MockInferenceClient(seed=1)

    from app.routing.signal_router import set_routing_mode
    set_routing_mode("production")

    session = create_streaming_session(
        client=client, seed=1,
        source="live", cluster_configs=CLUSTER_CONFIGS, scan_interval=30,
        splunk_configs=SPLUNK_CONFIGS,
    )
    session.start()
    _live_session_id = session.session_id
    return session


def get_live_session():
    if not _live_session_id:
        return None
    return get_streaming_session(_live_session_id)


def _get_synthetic():
    if not _synthetic_session_id:
        return None
    return get_synthetic_session(_synthetic_session_id)


def _get_current_session():
    """For observatory and other APIs that need any active session."""
    return get_live_session() or _get_synthetic()


class StartSessionRequest(BaseModel):
    mode: str = "mock"
    source: str = "synthetic"
    seed: int = 42
    clusters: int = 5
    failure_rate: float = 0.02
    concurrency: int = 10
    signals_per_second: int = 100
    routing_mode: str = "production"
    scan_interval: int = 30
    live_clusters: Optional[list] = None
    target_namespaces: Optional[list] = None
    industry: str = "basic"
    workload_type: Optional[str] = None


class UpdateParamsRequest(BaseModel):
    clusters: Optional[int] = None
    failure_rate: Optional[float] = None
    concurrency: Optional[int] = None
    signals_per_second: Optional[int] = None
    models_enabled: Optional[dict] = None


@router.post("/start", dependencies=[Depends(require_write_access)])
async def start_session(req: StartSessionRequest):
    """Start a synthetic session (Demo / Simulator). Live monitoring is always running."""
    global _synthetic_session_id

    # Stop any existing synthetic session
    old = _get_synthetic()
    if old:
        old.stop()

    if req.mode == "real":
        from app.inference.adapters import RealInferenceClient
        client = RealInferenceClient()
    else:
        from app.inference.client import MockInferenceClient
        client = MockInferenceClient(seed=req.seed)

    from app.routing.signal_router import set_industry, set_routing_mode, set_workload_type
    set_routing_mode(req.routing_mode)
    set_industry(req.industry)
    if req.workload_type:
        set_workload_type(req.workload_type)

    session = create_synthetic_session(client=client, seed=req.seed)
    session.update_params(
        clusters=req.clusters,
        failure_rate=req.failure_rate,
        concurrency=req.concurrency,
        signals_per_second=req.signals_per_second,
    )
    session.start()
    _synthetic_session_id = session.session_id

    # If target_namespaces specified, filter the live session's signal processing
    if req.target_namespaces:
        live = get_live_session()
        if live:
            live.target_namespaces = req.target_namespaces

    return {"session_id": session.session_id, "status": "started", "target_namespaces": req.target_namespaces}


@router.post("/signals/inject", dependencies=[Depends(require_write_access)])
async def inject_signal(body: dict):
    """Inject a signal directly into the live session's processing pipeline.

    Used by the platform dashboard to ensure DeepField analyzes a specific
    failure (e.g., a chaos-injected pod) rather than whatever is loudest.
    Does NOT affect live monitoring — the signal is added to the queue alongside
    real signals, not instead of them.
    """
    session = get_live_session() or _get_synthetic()
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    from datetime import datetime, timezone
    from uuid import uuid4

    from app.domain.models import RawSignal
    sig = RawSignal(
        signal_id=uuid4(),
        cluster_id=uuid4(),
        source=body.get("source", "injected"),
        signal_type=body.get("signal_type", "event_backoff"),
        resource_kind=body.get("resource_kind", "Pod"),
        resource_name=body.get("resource_name", ""),
        namespace=body.get("namespace", ""),
        raw_payload=body.get("evidence", {}),
        timestamp=datetime.now(timezone.utc),
    )
    session._signal_queue.append(sig)
    return {"injected": True, "queue_depth": len(session._signal_queue)}


@router.post("/update", dependencies=[Depends(require_write_access)])
async def update_params(req: UpdateParamsRequest):
    session = _get_synthetic()
    if not session:
        raise HTTPException(status_code=404, detail="No active session")
    updates = {k: v for k, v in req.dict().items() if v is not None}
    session.update_params(**updates)
    return {"status": "updated", "params": session.params.__dict__}


@router.post("/stop", dependencies=[Depends(require_write_access)])
async def stop_session():
    """Stop the synthetic session. Live monitoring keeps running."""
    global _synthetic_session_id
    session = _get_synthetic()
    if not session:
        return {"status": "no session"}
    session.stop()

    state = session.get_state()
    totals = state.get("totals", {})
    metrics = state.get("metrics", {})
    snapshots = state.get("snapshots", [])

    receipt = {
        "session_id": session.session_id,
        "status": "completed",
        "total_raw_signals": totals.get("raw_signals", 0),
        "total_reasoning_tasks": totals.get("reasoning_tasks", 0),
        "total_inference_calls": totals.get("inference_calls", 0),
        "cumulative_compression_ratio": totals.get("cumulative_compression_ratio", 0),
        "cumulative_escalation_pct": totals.get("cumulative_escalation_pct", 0),
        "final_projected_clusters": metrics.get("projected_clusters", 0),
        "final_compression_ratio": metrics.get("compression_ratio", 0),
        "final_params": state.get("params", {}),
        "avg_latency_ms": metrics.get("avg_latency_ms", 0),
        "avg_tps": metrics.get("avg_tps", 0),
        "peak_projected_clusters": max((s.get("projected_clusters", 0) for s in snapshots), default=0),
        "max_compression_ratio": max((s.get("compression_ratio", 0) for s in snapshots), default=0),
        "model_stats": state.get("model_stats", {}),
        "snapshots": snapshots,
    }

    return {"status": "stopped", "receipt": receipt}


@router.post("/reset", dependencies=[Depends(require_write_access)])
async def reset_session():
    """Reset synthetic session and clear state. Live monitoring unaffected."""
    global _synthetic_session_id
    session = _get_synthetic()
    if session:
        session.stop()
    _synthetic_session_id = None
    return {"status": "reset"}


@router.get("/state")
async def get_state():
    """Get synthetic session state (for Demo / Simulator)."""
    session = _get_synthetic()
    if not session:
        return {"status": "no_session"}
    return session.get_state()


@router.get("/live/state")
async def get_live_state():
    """Get live monitoring session state."""
    session = get_live_session()
    if not session:
        return {"status": "no_live_session"}
    return session.get_state()


@router.get("/cascade/stats")
async def get_cascade_stats():
    """Get cascade framework shadow mode statistics."""
    try:
        from app.session.streaming_session import _cascade_bridge
        if _cascade_bridge and _cascade_bridge.enabled:
            return {
                "stats": _cascade_bridge.get_stats(),
                "phi4": _cascade_bridge.get_phi4_summary(),
                "phi4_results": _cascade_bridge.get_phi4_results(10),
                "promotion_log": _cascade_bridge.get_promotion_log(30),
                "discovered_agents": _cascade_bridge.get_discovered_agents(),
            }
        return {"status": "cascade_bridge_not_enabled"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/cascade/precision")
async def get_cascade_precision(sample_size: int = 50):
    """Sample important signals and estimate precision using a second LLM pass."""
    try:
        from app.session.streaming_session import _cascade_bridge
        if not _cascade_bridge or not _cascade_bridge.enabled:
            return {"status": "cascade_bridge_not_enabled"}

        import random, json, httpx

        results = _cascade_bridge._phi4_results
        important = [r for r in results if r.get("classification", "") in
                     ("needs_attention", "real_incident")]
        if not important:
            return {"status": "no_important_signals_to_sample"}

        rng = random.Random(42)
        sampled = rng.sample(important, min(sample_size, len(important)))

        llm_url = os.getenv("LITELLM_API_BASE", "")
        llm_key = os.getenv("LITELLM_API_KEY", "")
        llm_model = os.getenv("CASCADE_LLM_MODEL", "granite-3-2-8b-instruct-cpu")

        if not llm_url:
            return {"status": "no_llm_configured", "sampled": len(sampled)}

        audit_prompt = (
            "You are auditing a signal classifier. It marked this signal as important. "
            "Was it RIGHT to escalate, or is this a false alarm? "
            "Respond with exactly one word: correct or false_alarm."
        )

        verdicts = []
        client = httpx.Client(timeout=30, verify=False)
        for sig in sampled:
            text = f"Signal '{sig['classification']}': {sig['signal_type']} {json.dumps({k: v for k, v in sig.items() if k not in ('classification', 'latency_ms')})}"
            try:
                r = client.post(f"{llm_url}/v1/chat/completions", json={
                    "model": llm_model,
                    "messages": [{"role": "system", "content": audit_prompt},
                                 {"role": "user", "content": text}],
                    "max_tokens": 5, "temperature": 0,
                }, headers={"Authorization": f"Bearer {llm_key}"})
                ans = r.json()["choices"][0]["message"]["content"].strip().lower()
                verdict = "true_important" if "correct" in ans else "false_important" if "false" in ans or "alarm" in ans else "inconclusive"
            except:
                verdict = "inconclusive"
            verdicts.append({"signal_type": sig["signal_type"], "classification": sig["classification"], "verdict": verdict})
        client.close()

        true_imp = sum(1 for v in verdicts if v["verdict"] == "true_important")
        false_imp = sum(1 for v in verdicts if v["verdict"] == "false_important")
        inconc = sum(1 for v in verdicts if v["verdict"] == "inconclusive")
        precision = true_imp / max(1, true_imp + false_imp)

        return {
            "precision": precision,
            "sampled": len(verdicts),
            "true_important": true_imp,
            "false_important": false_imp,
            "inconclusive": inconc,
            "samples": verdicts[:20],
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/cascade/promote")
async def run_cascade_promotion():
    """Trigger a promotion round for cascade agents."""
    try:
        from app.session.streaming_session import _cascade_bridge
        if _cascade_bridge and _cascade_bridge.enabled:
            return _cascade_bridge.run_promotion_round()
        return {"status": "cascade_bridge_not_enabled"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/cascade/replay")
async def start_replay(body: dict = {}):
    """Replay historical signals through the cascade to bootstrap knowledge."""
    try:
        from app.session.streaming_session import _cascade_bridge
        from app.cascade_replay import HistoricalReplay

        if not _cascade_bridge or not _cascade_bridge.enabled:
            return {"status": "cascade_bridge_not_enabled"}

        batch_size = body.get("batch_size", 1000)
        limit = body.get("limit", 100000)  # default 100K, not all 130M

        replay = HistoricalReplay(batch_size=batch_size, limit=limit)
        result = replay.run(_cascade_bridge, background=True)

        # Store replay instance for status checks
        global _active_replay
        _active_replay = replay
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/cascade/replay/status")
async def replay_status():
    """Get replay progress."""
    try:
        if _active_replay:
            return _active_replay.get_status()
        return {"status": "no replay running"}
    except Exception:
        return {"status": "no replay running"}


_active_replay = None


@router.post("/cascade/aap/start")
async def start_aap():
    """Start AAP cascade pipeline (separate from K8s)."""
    from app.cascade_bridge_aap import start_aap_cascade
    return start_aap_cascade()


@router.post("/cascade/aap/stop")
async def stop_aap():
    """Stop AAP cascade pipeline."""
    from app.cascade_bridge_aap import stop_aap_cascade
    return stop_aap_cascade()


@router.get("/cascade/aap/stats")
async def aap_stats():
    """Get AAP cascade stats (separate from K8s)."""
    from app.cascade_bridge_aap import get_aap_stats
    return get_aap_stats()
