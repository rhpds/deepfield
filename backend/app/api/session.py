"""Session API — separate live monitoring (auto-start) and synthetic (push-button)."""

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.auth import require_write_access

from app.session.synthetic_session import create_synthetic_session, get_synthetic_session
from app.session.streaming_session import create_streaming_session, get_streaming_session

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

    from app.routing.signal_router import set_routing_mode
    set_routing_mode(req.routing_mode)

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

    from app.domain.models import RawSignal
    from uuid import uuid4
    from datetime import datetime, timezone
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
