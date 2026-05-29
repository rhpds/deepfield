"""Remediation execution API — suggest + confirm pattern.

Only executes pre-approved command types against the cluster.
All commands are validated against an allowlist before execution.
"""

import os
import re
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/v1/remediation", tags=["remediation"])

ECOSYSTEM_NAMESPACES = {"deepfield", "stargate", "partner-ai-launchpad", "platform-dashboard", "intel-rh-demo"}
READ_ONLY_COMMANDS = {"get", "describe", "logs"}

ALLOWED_COMMANDS = {
    "get": "Read resource state",
    "describe": "Detailed resource info",
    "logs": "Container logs",
    "delete_pod": "Delete pod (triggers restart via controller)",
    "rollout_restart": "Restart deployment rollout",
    "scale": "Scale deployment replicas",
}

def _load_remediation_targets() -> dict:
    """Load remediation-allowed clusters from environment variables."""
    targets = {}
    for i in range(1, 5):
        name = os.getenv(f"CLUSTER_{i}_NAME", "")
        api_url = os.getenv(f"CLUSTER_{i}_API_URL", "")
        token = os.getenv(f"CLUSTER_{i}_TOKEN", "")
        allow_remediation = os.getenv(f"CLUSTER_{i}_ALLOW_REMEDIATION", "false").lower() == "true"
        if name and api_url and allow_remediation:
            targets[name] = {"api_url": api_url, "token": token}
    return targets


CLUSTER_APIS = _load_remediation_targets()


class ExecuteRequest(BaseModel):
    cluster: str
    namespace: str
    command: str
    resource_kind: str
    resource_name: str
    args: Optional[dict] = None


@router.get("/commands")
async def list_commands():
    return {"allowed_commands": ALLOWED_COMMANDS}


@router.post("/execute")
async def execute_command(req: ExecuteRequest):
    if req.command not in ALLOWED_COMMANDS:
        return {"status": "error", "command": req.command, "output": f"Command '{req.command}' not allowed. Allowed: {list(ALLOWED_COMMANDS.keys())}"}

    cluster_cfg = CLUSTER_APIS.get(req.cluster)
    if not cluster_cfg:
        return {"status": "error", "command": req.command, "output": f"Unknown cluster: {req.cluster}. Known: {list(CLUSTER_APIS.keys())}"}

    if not cluster_cfg["token"]:
        return {"status": "error", "command": req.command, "output": f"No token configured for cluster {req.cluster}"}

    if req.resource_name and not re.match(r'^[a-zA-Z0-9._/-]+$', req.resource_name):
        return {"status": "error", "command": req.command, "output": f"Invalid resource name: {req.resource_name}"}
    if req.namespace and not re.match(r'^[a-zA-Z0-9._-]+$', req.namespace):
        return {"status": "error", "command": req.command, "output": f"Invalid namespace: {req.namespace}"}

    if req.command not in READ_ONLY_COMMANDS and req.namespace not in ECOSYSTEM_NAMESPACES:
        return {"status": "blocked", "command": req.command,
                "output": f"Execution blocked: namespace '{req.namespace}' is outside the ecosystem. "
                          f"Remediation actions are only allowed in: {', '.join(sorted(ECOSYSTEM_NAMESPACES))}. "
                          f"Use 'get', 'describe', or 'logs' for read-only access to any namespace."}

    api_url = cluster_cfg["api_url"]
    token = cluster_cfg["token"]
    headers = {"Authorization": f"Bearer {token}"}
    kind_lower = req.resource_kind.lower() + "s"

    try:
        with httpx.Client(timeout=30.0, verify=False) as client:
            if req.command == "get":
                if req.resource_name and req.resource_name != "unknown":
                    path = f"/api/v1/namespaces/{req.namespace}/{kind_lower}/{req.resource_name}"
                else:
                    path = f"/api/v1/namespaces/{req.namespace}/{kind_lower}"
                resp = client.get(f"{api_url}{path}", headers=headers)
                result = {"status": "ok", "command": req.command, "output": _safe_output(resp)}
                _persist_remediation(req, result)
                return result

            elif req.command == "describe":
                path = f"/api/v1/namespaces/{req.namespace}/{kind_lower}/{req.resource_name}"
                resp = client.get(f"{api_url}{path}", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return {"status": "ok", "command": req.command, "output": _describe_resource(data)}
                return {"status": "error", "output": f"{resp.status_code}: {resp.text[:500]}"}

            elif req.command == "logs":
                container = (req.args or {}).get("container", "")
                path = f"/api/v1/namespaces/{req.namespace}/pods/{req.resource_name}/log"
                params = {"tailLines": "100"}
                if container:
                    params["container"] = container
                resp = client.get(f"{api_url}{path}", headers=headers, params=params)
                return {"status": "ok", "command": req.command, "output": resp.text[:5000]}

            elif req.command == "delete_pod":
                path = f"/api/v1/namespaces/{req.namespace}/pods/{req.resource_name}"
                resp = client.delete(f"{api_url}{path}", headers=headers)
                return {"status": "ok", "command": req.command, "output": f"Pod {req.resource_name} deleted (status {resp.status_code})"}

            elif req.command == "rollout_restart":
                path = f"/apis/apps/v1/namespaces/{req.namespace}/deployments/{req.resource_name}"
                resp = client.get(f"{api_url}{path}", headers=headers)
                if resp.status_code != 200:
                    return {"status": "error", "output": f"Deployment not found: {resp.status_code}"}
                deploy = resp.json()
                annotations = deploy.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations", {})
                from datetime import datetime, timezone
                annotations["kubectl.kubernetes.io/restartedAt"] = datetime.now(timezone.utc).isoformat()
                deploy["spec"]["template"]["metadata"]["annotations"] = annotations
                resp = client.put(f"{api_url}{path}", headers={**headers, "Content-Type": "application/json"}, json=deploy)
                return {"status": "ok", "command": req.command, "output": f"Deployment {req.resource_name} rollout restarted (status {resp.status_code})"}

            elif req.command == "scale":
                replicas = (req.args or {}).get("replicas", 1)
                path = f"/apis/apps/v1/namespaces/{req.namespace}/deployments/{req.resource_name}/scale"
                resp = client.get(f"{api_url}{path}", headers=headers)
                if resp.status_code != 200:
                    return {"status": "error", "output": f"Scale resource not found: {resp.status_code}"}
                scale = resp.json()
                scale["spec"]["replicas"] = int(replicas)
                resp = client.put(f"{api_url}{path}", headers={**headers, "Content-Type": "application/json"}, json=scale)
                return {"status": "ok", "command": req.command, "output": f"Scaled {req.resource_name} to {replicas} replicas (status {resp.status_code})"}

    except Exception as e:
        result = {"status": "error", "command": req.command, "output": str(e)[:500]}
        _persist_remediation(req, result)
        return result


def _persist_remediation(req: ExecuteRequest, result: dict):
    from app.db import enqueue_write
    enqueue_write("remediations", {
        "cluster": req.cluster,
        "namespace": req.namespace,
        "command": req.command,
        "resource_kind": req.resource_kind,
        "resource_name": req.resource_name,
        "status": result.get("status", "unknown"),
        "output": str(result.get("output", ""))[:2000],
    })


def _safe_output(resp) -> str:
    if resp.status_code == 200:
        try:
            data = resp.json()
            if "items" in data:
                lines = []
                for item in data["items"][:50]:
                    meta = item.get("metadata", {})
                    status = item.get("status", {})
                    name = meta.get("name", "")
                    phase = status.get("phase", "")
                    restarts = ""
                    for cs in status.get("containerStatuses", []):
                        if cs.get("restartCount", 0) > 0:
                            restarts = f" restarts={cs['restartCount']}"
                    lines.append(f"{name}  {phase}{restarts}")
                return f"{len(data['items'])} resources:\n" + "\n".join(lines)
            return _describe_resource(data)
        except Exception:
            return resp.text[:2000]
    return f"Error {resp.status_code}: {resp.text[:500]}"


def _describe_resource(data: dict) -> str:
    meta = data.get("metadata", {})
    status = data.get("status", {})
    spec = data.get("spec", {})
    lines = [
        f"Name: {meta.get('name', '')}",
        f"Namespace: {meta.get('namespace', '')}",
        f"Labels: {meta.get('labels', {})}",
        f"Created: {meta.get('creationTimestamp', '')}",
    ]
    owners = meta.get("ownerReferences", [])
    if owners:
        lines.append(f"Owner: {owners[0].get('kind', '')}/{owners[0].get('name', '')}")
    if "nodeName" in spec:
        lines.append(f"Node: {spec['nodeName']}")
    if "phase" in status:
        lines.append(f"Phase: {status['phase']}")
    if "conditions" in status:
        for c in status["conditions"][-5:]:
            lines.append(f"  {c.get('type', '')}: {c.get('status', '')} ({c.get('reason', '')})")
    for cs in status.get("containerStatuses", []):
        lines.append(f"Container: {cs.get('name', '')} image={cs.get('image', '')} restarts={cs.get('restartCount', 0)}")
        state = cs.get("state", {})
        for k, v in state.items():
            lines.append(f"  State: {k} {v}")
    return "\n".join(lines)
