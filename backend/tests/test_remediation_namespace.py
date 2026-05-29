"""Tests for remediation namespace enforcement logic.

Validates that mutating commands are blocked outside ecosystem namespaces,
while read-only commands pass through, and unknown commands are rejected.
"""

import pytest
import pytest_asyncio
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from app.main import app


MOCK_CLUSTER_APIS = {
    "test-cluster": {"api_url": "https://fake-api:6443", "token": "fake-token"},
}


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _execute_payload(command: str, namespace: str, **overrides) -> dict:
    payload = {
        "cluster": "test-cluster",
        "namespace": namespace,
        "command": command,
        "resource_kind": "Pod",
        "resource_name": "test-pod",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
@patch("app.api.remediation.CLUSTER_APIS", MOCK_CLUSTER_APIS)
async def test_get_allowed_any_namespace(client):
    """GET command on kube-system should NOT be blocked."""
    resp = await client.post(
        "/api/v1/remediation/execute",
        json=_execute_payload("get", "kube-system"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] != "blocked"


@pytest.mark.asyncio
@patch("app.api.remediation.CLUSTER_APIS", MOCK_CLUSTER_APIS)
async def test_logs_allowed_non_ecosystem(client):
    """logs command on monitoring namespace should NOT be blocked."""
    resp = await client.post(
        "/api/v1/remediation/execute",
        json=_execute_payload("logs", "monitoring"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] != "blocked"


@pytest.mark.asyncio
@patch("app.api.remediation.CLUSTER_APIS", MOCK_CLUSTER_APIS)
async def test_delete_pod_blocked_non_ecosystem(client):
    """delete_pod on kube-system returns status=blocked."""
    resp = await client.post(
        "/api/v1/remediation/execute",
        json=_execute_payload("delete_pod", "kube-system"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"


@pytest.mark.asyncio
@patch("app.api.remediation.CLUSTER_APIS", MOCK_CLUSTER_APIS)
async def test_delete_pod_allowed_ecosystem(client):
    """delete_pod on deepfield should NOT be blocked (may fail on K8s call)."""
    resp = await client.post(
        "/api/v1/remediation/execute",
        json=_execute_payload("delete_pod", "deepfield"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] != "blocked"


@pytest.mark.asyncio
@patch("app.api.remediation.CLUSTER_APIS", MOCK_CLUSTER_APIS)
async def test_rollout_restart_blocked(client):
    """rollout_restart on default namespace returns status=blocked."""
    resp = await client.post(
        "/api/v1/remediation/execute",
        json=_execute_payload("rollout_restart", "default", resource_kind="Deployment"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"


@pytest.mark.asyncio
@patch("app.api.remediation.CLUSTER_APIS", MOCK_CLUSTER_APIS)
async def test_scale_blocked(client):
    """scale on openshift-operators returns status=blocked."""
    resp = await client.post(
        "/api/v1/remediation/execute",
        json=_execute_payload("scale", "openshift-operators", resource_kind="Deployment"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"


@pytest.mark.asyncio
@patch("app.api.remediation.CLUSTER_APIS", MOCK_CLUSTER_APIS)
async def test_unknown_command_rejected(client):
    """exec command returns status=error."""
    resp = await client.post(
        "/api/v1/remediation/execute",
        json=_execute_payload("exec", "deepfield"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
