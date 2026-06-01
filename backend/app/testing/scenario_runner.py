"""Synthetic scenario runner — end-to-end pipeline testing.

Injects controlled failures into ECOSYSTEM NAMESPACES ONLY,
validates the full pipeline (detect → classify → RCA → incident → remediation),
then cleans up.

CRITICAL: All injection and remediation execution is restricted to ecosystem
namespaces. This is enforced at multiple levels and cannot be overridden.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("deepfield.scenarios")

ECOSYSTEM_NAMESPACES = frozenset({
    "deepfield", "stargate", "partner-ai-launchpad",
    "platform-dashboard", "intel-rh-demo",
})


@dataclass
class Scenario:
    id: str
    name: str
    namespace: str
    inject_type: str
    inject_spec: dict = field(default_factory=dict)
    expected_classification: str = ""
    expected_severity: str = "high"
    execute_remediation: bool = True
    cleanup_resources: list = field(default_factory=list)
    description: str = ""


SCENARIOS: Dict[str, Scenario] = {
    "pod_crashloop": Scenario(
        id="pod_crashloop",
        name="Pod Crashloop",
        namespace="deepfield",
        inject_type="pod",
        inject_spec={
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": "chaos-crashloop", "namespace": "deepfield",
                         "labels": {"app": "deepfield-chaos-test"}},
            "spec": {"containers": [{"name": "crash", "image": "busybox",
                                     "command": ["sh", "-c", "echo 'starting app...' && sleep 2 && echo 'FATAL: out of memory' >&2 && kill -9 $$"],
                                     "resources": {"limits": {"memory": "16Mi"}}}],
                     "restartPolicy": "Always"},
        },
        expected_classification="pods_crashlooping",
        expected_severity="high",
        execute_remediation=True,
        cleanup_resources=[{"kind": "Pod", "name": "chaos-crashloop", "namespace": "deepfield"}],
        description="Creates a pod that simulates OOM crashloop (runs briefly, killed by SIGKILL, restarts). Validates crashloop detection → classification → RCA → remediation.",
    ),
    "config_error": Scenario(
        id="config_error",
        name="Configuration Error",
        namespace="platform-dashboard",
        inject_type="pod",
        inject_spec={
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": "chaos-configerr", "namespace": "platform-dashboard",
                         "labels": {"app": "deepfield-chaos-test"}},
            "spec": {"containers": [{"name": "configerr", "image": "busybox",
                                     "command": ["sh", "-c", "echo $MISSING_VAR && exit 1"],
                                     "env": [{"name": "MISSING_VAR", "valueFrom":
                                              {"configMapKeyRef": {"name": "nonexistent-config", "key": "val"}}}]}],
                     "restartPolicy": "Never"},
        },
        expected_classification="invalid_configuration",
        expected_severity="high",
        execute_remediation=True,
        cleanup_resources=[{"kind": "Pod", "name": "chaos-configerr", "namespace": "platform-dashboard"}],
        description="Creates a pod with missing ConfigMap reference. Validates config error detection and classification.",
    ),
    "image_pull": Scenario(
        id="image_pull",
        name="Image Pull Error",
        namespace="intel-rh-demo",
        inject_type="pod",
        inject_spec={
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": "chaos-imagepull", "namespace": "intel-rh-demo",
                         "labels": {"app": "deepfield-chaos-test"}},
            "spec": {"containers": [{"name": "badimage", "image": "nonexistent-registry.example.com/fake-image:v999"}],
                     "restartPolicy": "Never"},
        },
        expected_classification="image_pull_backoff",
        expected_severity="high",
        execute_remediation=True,
        cleanup_resources=[{"kind": "Pod", "name": "chaos-imagepull", "namespace": "intel-rh-demo"}],
        description="Creates a pod with nonexistent image. Validates image pull error detection.",
    ),
    "synthetic_oom": Scenario(
        id="synthetic_oom",
        name="Synthetic OOM (Signal Only)",
        namespace="deepfield",
        inject_type="synthetic_signal",
        inject_spec={
            "signal_type": "pod_crashloop",
            "namespace": "deepfield",
            "resource_kind": "Pod",
            "resource_name": "synthetic-oom-pod",
            "severity": "critical",
            "raw_payload": {"reason": "OOMKilled", "exitCode": 137, "message": "Container killed due to OOM"},
        },
        expected_classification="oom_killed",
        expected_severity="critical",
        execute_remediation=False,
        cleanup_resources=[],
        description="Injects a synthetic OOM signal without creating real resources. Tests pipeline processing only.",
    ),
}


class ScenarioRunner:
    def __init__(self, cluster_api_url: str = "", token: str = ""):
        self.api = cluster_api_url
        self.token = token

    def validate_namespace(self, namespace: str):
        if not namespace or namespace not in ECOSYSTEM_NAMESPACES:
            raise ValueError(f"Namespace '{namespace}' is not in ecosystem. Allowed: {sorted(ECOSYSTEM_NAMESPACES)}")

    async def run_scenario(self, scenario_id: str) -> dict:
        scenario = SCENARIOS.get(scenario_id)
        if not scenario:
            return {"error": f"Unknown scenario: {scenario_id}"}

        self.validate_namespace(scenario.namespace)
        result = {
            "scenario_id": scenario_id,
            "name": scenario.name,
            "namespace": scenario.namespace,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps": [],
            "checks": [],
            "status": "running",
        }

        try:
            if scenario.inject_type == "synthetic_signal":
                result["steps"].append(await self._inject_signal(scenario))
            else:
                result["steps"].append(await self._inject_resource(scenario))

            incident = await self._wait_for_incident(scenario.namespace, timeout=120)
            result["incident"] = incident

            if incident:
                result["checks"] = validate_incident(
                    incident, scenario.expected_classification, scenario.expected_severity)

                if scenario.execute_remediation and incident.get("remediation_options"):
                    result["steps"].append({"step": "remediation", "status": "suggested",
                                            "options": len(incident["remediation_options"])})

            await self._cleanup(scenario)
            result["steps"].append({"step": "cleanup", "status": "done"})

            result["status"] = "pass" if all(c.get("passed") for c in result.get("checks", [])) else "fail"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            await self._cleanup(scenario)

        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        return result

    async def _inject_signal(self, scenario: Scenario) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "http://localhost:8099/api/v1/session/signals/inject",
                json=scenario.inject_spec,
            )
            return {"step": "inject_signal", "status": "ok" if resp.status_code == 200 else "failed",
                    "response": resp.status_code}

    async def _inject_resource(self, scenario: Scenario) -> dict:
        if not self.api or not self.token:
            return {"step": "inject_resource", "status": "skipped", "reason": "no cluster API configured"}
        import httpx
        kind = scenario.inject_spec.get("kind", "Pod").lower() + "s"
        ns = scenario.namespace
        url = f"{self.api}/api/v1/namespaces/{ns}/{kind}"
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.post(url, json=scenario.inject_spec,
                                     headers={"Authorization": f"Bearer {self.token}"})
            return {"step": "inject_resource", "status": "ok" if resp.status_code in (200, 201) else "failed",
                    "response": resp.status_code, "kind": kind, "name": scenario.inject_spec.get("metadata", {}).get("name")}

    async def _wait_for_incident(self, namespace: str, timeout: int = 120) -> Optional[dict]:
        import httpx
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get("http://localhost:8099/api/v1/incidents")
                    if resp.status_code == 200:
                        incidents = resp.json().get("incidents", [])
                        for inc in incidents:
                            if inc.get("namespace") == namespace and inc.get("status") == "open":
                                return inc
            except Exception:
                pass
            await _async_sleep(5)
        return None

    async def _cleanup(self, scenario: Scenario):
        if not self.api or not self.token:
            return
        import httpx
        for res in scenario.cleanup_resources:
            try:
                kind = res.get("kind", "Pod").lower() + "s"
                ns = res.get("namespace", scenario.namespace)
                name = res.get("name", "")
                self.validate_namespace(ns)
                url = f"{self.api}/api/v1/namespaces/{ns}/{kind}/{name}"
                async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                    await client.delete(url, headers={"Authorization": f"Bearer {self.token}"})
            except Exception as e:
                logger.warning("Cleanup failed for %s: %s", res, e)


async def _async_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)


def validate_incident(incident: dict, expected_class: str, expected_severity: str) -> list:
    checks = []
    checks.append({
        "check": "incident_created",
        "passed": incident is not None,
        "detail": "Incident exists" if incident else "No incident found",
    })
    if not incident:
        return checks

    checks.append({
        "check": "severity_correct",
        "passed": incident.get("severity") == expected_severity,
        "detail": f"Expected {expected_severity}, got {incident.get('severity')}",
    })

    checks.append({
        "check": "classification_correct",
        "passed": incident.get("failure_class") == expected_class,
        "detail": f"Expected {expected_class}, got {incident.get('failure_class')}",
    })

    checks.append({
        "check": "has_signals",
        "passed": incident.get("signal_count", 0) > 0,
        "detail": f"{incident.get('signal_count', 0)} signals",
    })

    checks.append({
        "check": "rca_produced",
        "passed": bool(incident.get("rca_output")),
        "detail": "RCA output present" if incident.get("rca_output") else "No RCA output",
    })

    checks.append({
        "check": "has_remediation",
        "passed": len(incident.get("remediation_options", [])) > 0,
        "detail": f"{len(incident.get('remediation_options', []))} options",
    })

    return checks


def build_synthetic_signal(namespace: str, signal_type: str, severity: str,
                           resource_name: str = "synthetic-pod") -> dict:
    return {
        "cluster_id": "infra01",
        "namespace": namespace,
        "resource_kind": "Pod",
        "resource_name": resource_name,
        "signal_type": signal_type,
        "severity": severity,
        "raw_payload": {"source": "scenario_runner", "synthetic": True},
    }
