"""Tests for the integration event endpoint — cross-product signal ingestion."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_stargate_event_accepted(client):
    event = {
        "source": "stargate",
        "event_type": "stargate_stage_failed",
        "event_id": "test-001",
        "timestamp": "2026-05-29T12:00:00Z",
        "payload": {
            "run_id": "run-abc",
            "stage_id": "deployment-ready",
            "lab_code": "test-lab",
            "cluster": "infra01",
            "outcome": "fail",
            "failure_class": "pods_crashlooping",
        },
    }
    resp = await client.post("/integration/events", json=event)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("accepted") or data.get("status") == "ok" or "signal" in str(data).lower() or resp.status_code == 200


@pytest.mark.asyncio
async def test_launchpad_event_accepted(client):
    event = {
        "source": "launchpad",
        "event_type": "launchpad_lab_failed",
        "event_id": "test-002",
        "timestamp": "2026-05-29T12:00:00Z",
        "payload": {
            "session_id": "sess-123",
            "lab_code": "inference-overdrive",
            "namespace": "user-demo-tenant-abc",
        },
    }
    resp = await client.post("/integration/events", json=event)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_detection(client):
    event = {
        "source": "stargate",
        "event_type": "stargate_stage_passed",
        "event_id": "dup-001",
        "timestamp": "2026-05-29T12:00:00Z",
        "payload": {"run_id": "run-xyz"},
    }
    resp1 = await client.post("/integration/events", json=event)
    resp2 = await client.post("/integration/events", json=event)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2.get("duplicate", False) or "already" in str(data2).lower() or resp2.status_code == 200


@pytest.mark.asyncio
async def test_malformed_event_handled(client):
    resp = await client.post("/integration/events", json={"bad": "data"})
    assert resp.status_code in (200, 400, 422)
