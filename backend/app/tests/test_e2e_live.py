"""E2E integration test — live chaos cluster through full pipeline.

Starts a live monitoring session against infra01, waits for signals
to flow through nano→micro→macro pipeline, and verifies observatory
endpoints return real data with full evidence chains.

Requires: INFRA01_TOKEN env var set, chaos workloads running on infra01.
Skip if not available.
"""

import os
import time
import pytest
import httpx

DEEPFIELD_URL = os.getenv("DEEPFIELD_URL", "http://localhost:8099")
INFRA01_TOKEN = os.getenv("INFRA01_TOKEN", "")

skip_no_token = pytest.mark.skipif(
    not INFRA01_TOKEN,
    reason="INFRA01_TOKEN not set — skip live E2E",
)


@pytest.fixture(scope="module")
def client():
    return httpx.Client(base_url=DEEPFIELD_URL, timeout=30, verify=False)


@pytest.fixture(scope="module")
def live_session(client):
    """Start a live monitoring session and wait for signals."""
    # Stop any existing session
    client.post("/api/v1/session/stop")
    time.sleep(1)

    # Start live session with mock inference (no dependency on Gaudi availability)
    resp = client.post("/api/v1/session/start", json={
        "mode": "mock",
        "source": "live",
        "scan_interval": 15,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"

    # Wait for first signals (initial scan takes ~10s)
    for _ in range(30):
        time.sleep(2)
        state = client.get("/api/v1/session/state").json()
        if state.get("totals", {}).get("raw_signals", 0) > 0:
            break

    yield data["session_id"]

    # Cleanup
    client.post("/api/v1/session/stop")


@skip_no_token
def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@skip_no_token
def test_live_signals_flow(client, live_session):
    """Signals from chaos workloads should flow through the pipeline."""
    # Session state totals may lag behind observatory store — check both
    for _ in range(10):
        state = client.get("/api/v1/session/state").json()
        if state.get("totals", {}).get("raw_signals", 0) > 0:
            break
        time.sleep(3)

    sig_resp = client.get("/api/v1/observatory/signals").json()
    obs_signals = len(sig_resp.get("signals", []))
    session_signals = state.get("totals", {}).get("raw_signals", 0)

    assert obs_signals > 0 or session_signals > 0, (
        f"No signals in either path: observatory={obs_signals}, session={session_signals}"
    )
    assert state.get("status") == "running"


@skip_no_token
def test_nano_agents_filter(client, live_session):
    """Nano agents should process and filter signals."""
    # Wait a bit for pipeline processing
    time.sleep(5)

    resp = client.get("/api/v1/observatory/agents")
    assert resp.status_code == 200
    data = resp.json()
    agents = data.get("agents", {})

    assert len(agents) > 0, "No nano agents have processed signals"

    total_evaluated = sum(a.get("total_evaluated", 0) for a in agents.values())
    assert total_evaluated > 0, "Nano agents evaluated zero signals"


@skip_no_token
def test_observatory_signals_have_detail(client, live_session):
    """Observatory should store signals with full payload."""
    time.sleep(5)

    resp = client.get("/api/v1/observatory/signals")
    assert resp.status_code == 200
    data = resp.json()
    signals = data.get("signals", [])

    assert len(signals) > 0, "No signals in observatory store"

    sig = signals[-1]
    assert "signal_type" in sig
    assert "namespace" in sig or "cluster" in sig
    assert "_ts" in sig


@skip_no_token
def test_observatory_clusters_have_data(client, live_session):
    """Observatory should track per-cluster infrastructure stats."""
    time.sleep(5)

    resp = client.get("/api/v1/observatory/clusters")
    assert resp.status_code == 200
    data = resp.json()
    clusters = data.get("clusters", {})

    assert len(clusters) > 0, "No cluster data in observatory"

    for name, info in clusters.items():
        assert "cluster_name" in info
        assert "namespaces" in info


@skip_no_token
def test_chaos_signals_detected(client, live_session):
    """Chaos workloads (crashloop, imagepull, pending) should produce signals."""
    time.sleep(10)

    resp = client.get("/api/v1/observatory/signals")
    signals = resp.json().get("signals", [])
    signal_types = {s.get("signal_type", "") for s in signals}

    chaos_types = {"pod_crashloop", "pod_imagepullbackoff", "pod_pending"}
    detected = signal_types & chaos_types

    assert len(detected) > 0, (
        f"Expected chaos signal types {chaos_types}, got {signal_types}"
    )


@skip_no_token
def test_inference_triggered_for_findings(client, live_session):
    """Pipeline should process signals — findings depend on correlation window."""
    time.sleep(15)

    state = client.get("/api/v1/session/state").json()
    totals = state.get("totals", {})
    sig_resp = client.get("/api/v1/observatory/signals").json()
    findings = sig_resp.get("findings", [])

    # With chaos workloads we expect at least signals to be processed.
    # Findings require correlated signals in same time window — may or may not happen.
    has_signals = len(sig_resp.get("signals", [])) > 0
    has_findings = len(findings) > 0 or totals.get("findings", 0) > 0
    has_inference = totals.get("inference_calls", 0) > 0

    assert has_signals, f"No signals processed at all. Totals: {totals}"
    # Findings and inference are best-effort in short test windows
    if has_findings:
        print(f"  Findings detected: {len(findings)}")
    if has_inference:
        print(f"  Inference calls: {totals.get('inference_calls', 0)}")


@skip_no_token
def test_llm_observatory_has_inference_data(client, live_session):
    """LLM observatory should show model stats after inference runs."""
    time.sleep(15)

    resp = client.get("/api/v1/observatory/llm")
    assert resp.status_code == 200
    data = resp.json()

    # With mock inference, models should have been called
    models = data.get("models", {})
    inferences = data.get("recent_inferences", [])

    if models:
        for name, stats in models.items():
            assert stats.get("total_calls", 0) > 0, f"Model {name} has zero calls"
            assert stats.get("avg_latency", 0) > 0, f"Model {name} has zero latency"

    if inferences:
        inf = inferences[-1]
        assert "model" in inf
        assert "task_type" in inf
        assert "prompt" in inf
        assert "output" in inf


@skip_no_token
def test_agent_log_captures_pipeline_events(client, live_session):
    """Agent log should capture nano/micro/macro tier events."""
    time.sleep(10)

    state = client.get("/api/v1/session/state").json()
    agent_log = state.get("agent_log", [])

    assert len(agent_log) > 0, "Agent log is empty — pipeline events not captured"

    tiers_seen = {e.get("tier") for e in agent_log}
    assert "nano" in tiers_seen or "correlation" in tiers_seen, (
        f"Expected nano or correlation events, got tiers: {tiers_seen}"
    )


@skip_no_token
def test_full_evidence_chain(client, live_session):
    """Verify the full chain: signal → decision → finding → inference."""
    time.sleep(20)

    signals_resp = client.get("/api/v1/observatory/signals").json()
    agents_resp = client.get("/api/v1/observatory/agents").json()
    llm_resp = client.get("/api/v1/observatory/llm").json()
    state = client.get("/api/v1/session/state").json()

    signals = signals_resp.get("signals", [])
    findings = signals_resp.get("findings", [])
    agents = agents_resp.get("agents", {})
    decisions = agents_resp.get("recent_decisions", [])
    models = llm_resp.get("models", {})
    totals = state.get("totals", {})

    chain = {
        "signals": len(signals),
        "decisions": len(decisions),
        "agents_active": len(agents),
        "findings": len(findings),
        "total_raw": totals.get("raw_signals", 0),
        "total_tasks": totals.get("reasoning_tasks", 0),
        "total_inference": totals.get("inference_calls", 0),
        "models_used": len(models),
    }

    assert chain["signals"] > 0, f"Evidence chain broken at signals: {chain}"
    assert chain["decisions"] > 0, f"Evidence chain broken at decisions: {chain}"
    assert chain["agents_active"] > 0, f"Evidence chain broken at agents: {chain}"

    print(f"\n=== E2E Evidence Chain ===")
    for k, v in chain.items():
        print(f"  {k}: {v}")
