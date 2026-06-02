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
    "platform-dashboard", "intel-rh-demo", "deepfield-e2e",
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
        namespace="deepfield-e2e",
        inject_type="multi_pod",
        inject_spec={
            "pods": [
                {"apiVersion": "v1", "kind": "Pod",
                 "metadata": {"name": "chaos-crash-1", "namespace": "deepfield-e2e", "labels": {"app": "deepfield-chaos-test"}},
                 "spec": {"containers": [{"name": "crash", "image": "busybox",
                          "command": ["sh", "-c", "echo 'app starting...' && sleep 1 && kill -9 $$"]}],
                          "restartPolicy": "Always"}},
                {"apiVersion": "v1", "kind": "Pod",
                 "metadata": {"name": "chaos-crash-2", "namespace": "deepfield-e2e", "labels": {"app": "deepfield-chaos-test"}},
                 "spec": {"containers": [{"name": "crash", "image": "busybox",
                          "command": ["sh", "-c", "echo 'worker starting...' && sleep 1 && kill -11 $$"]}],
                          "restartPolicy": "Always"}},
                {"apiVersion": "v1", "kind": "Pod",
                 "metadata": {"name": "chaos-crash-3", "namespace": "deepfield-e2e", "labels": {"app": "deepfield-chaos-test"}},
                 "spec": {"containers": [{"name": "crash", "image": "busybox",
                          "command": ["sh", "-c", "echo 'sidecar starting...' && sleep 1 && exit 137"]}],
                          "restartPolicy": "Always"}},
            ],
        },
        expected_classification="pods_crashlooping",
        expected_severity="high",
        execute_remediation=True,
        cleanup_resources=[
            {"kind": "Pod", "name": "chaos-crash-1", "namespace": "deepfield-e2e"},
            {"kind": "Pod", "name": "chaos-crash-2", "namespace": "deepfield-e2e"},
            {"kind": "Pod", "name": "chaos-crash-3", "namespace": "deepfield-e2e"},
        ],
        description="Creates 3 crashing pods in deepfield-e2e namespace. Multiple failures trigger correlation → RCA → incident with remediation.",
    ),
    "config_error": Scenario(
        id="config_error",
        name="Configuration Error",
        namespace="platform-dashboard",
        inject_type="pod",
        inject_spec={
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": "chaos-configerr", "namespace": "deepfield-e2e",
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
        cleanup_resources=[{"kind": "Pod", "name": "chaos-configerr", "namespace": "deepfield-e2e"}],
        description="Creates a pod with missing ConfigMap reference. Validates config error detection and classification.",
    ),
    "image_pull": Scenario(
        id="image_pull",
        name="Image Pull Error",
        namespace="intel-rh-demo",
        inject_type="pod",
        inject_spec={
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": "chaos-imagepull", "namespace": "deepfield-e2e",
                         "labels": {"app": "deepfield-chaos-test"}},
            "spec": {"containers": [{"name": "badimage", "image": "nonexistent-registry.example.com/fake-image:v999"}],
                     "restartPolicy": "Never"},
        },
        expected_classification="image_pull_backoff",
        expected_severity="high",
        execute_remediation=True,
        cleanup_resources=[{"kind": "Pod", "name": "chaos-imagepull", "namespace": "deepfield-e2e"}],
        description="Creates a pod with nonexistent image. Validates image pull error detection.",
    ),
    "synthetic_oom": Scenario(
        id="synthetic_oom",
        name="Synthetic OOM (Signal Only)",
        namespace="deepfield-e2e",
        inject_type="synthetic_multi",
        inject_spec={
            "signals": [
                {"signal_type": "pod_crashloop", "namespace": "deepfield-e2e", "resource_kind": "Pod",
                 "resource_name": "synthetic-oom-pod-1", "severity": "critical",
                 "raw_payload": {"reason": "OOMKilled", "exitCode": 137}},
                {"signal_type": "pod_crashloop", "namespace": "deepfield-e2e", "resource_kind": "Pod",
                 "resource_name": "synthetic-oom-pod-2", "severity": "critical",
                 "raw_payload": {"reason": "OOMKilled", "exitCode": 137}},
                {"signal_type": "event_backoff", "namespace": "deepfield-e2e", "resource_kind": "Pod",
                 "resource_name": "synthetic-oom-pod-1", "severity": "high",
                 "raw_payload": {"reason": "BackOff", "message": "Back-off restarting failed container"}},
            ],
        },
        expected_classification="oom_killed",
        expected_severity="critical",
        execute_remediation=False,
        cleanup_resources=[],
        description="Injects 3 synthetic OOM/crashloop signals. Tests full pipeline: correlation → inference → incident.",
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
            # Resolve any existing open incident for this namespace so we get a fresh one
            await self._resolve_existing_incidents(scenario.namespace)
            result["steps"].append({"step": "clear_existing", "status": "done"})

            if scenario.inject_type == "multi_pod":
                result["steps"].append(await self._inject_multi_pods(scenario))
            elif scenario.inject_type == "synthetic_multi":
                result["steps"].append(await self._inject_multi_signals(scenario))
            elif scenario.inject_type == "synthetic_signal":
                result["steps"].append(await self._inject_signal(scenario))
            else:
                result["steps"].append(await self._inject_resource(scenario))

            incident = await self._wait_for_incident(scenario.namespace)
            result["incident"] = incident

            if incident:
                result["checks"] = validate_incident(
                    incident, scenario.expected_classification, scenario.expected_severity)

                if scenario.execute_remediation and incident.get("remediation_options"):
                    result["steps"].append({"step": "remediation", "status": "suggested",
                                            "options": len(incident["remediation_options"])})

            await self._cleanup(scenario)
            result["steps"].append({"step": "cleanup", "status": "done"})

            checks = result.get("checks", [])
            if not checks:
                result["status"] = "no_incident"
            elif all(c.get("passed") for c in checks):
                result["status"] = "pass"
            else:
                result["status"] = "fail"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            await self._cleanup(scenario)

        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        return result

    async def _inject_multi_pods(self, scenario: Scenario) -> dict:
        """Inject multiple pods to generate enough signals for correlation."""
        if not self.api or not self.token:
            return {"step": "inject_multi_pods", "status": "skipped", "reason": "no cluster API"}
        import httpx
        pods = scenario.inject_spec.get("pods", [])
        created = 0
        for pod_spec in pods:
            ns = pod_spec.get("metadata", {}).get("namespace", scenario.namespace)
            self.validate_namespace(ns)
            try:
                async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                    resp = await client.post(
                        f"{self.api}/api/v1/namespaces/{ns}/pods",
                        json=pod_spec,
                        headers={"Authorization": f"Bearer {self.token}"})
                    if resp.status_code in (200, 201):
                        created += 1
            except Exception:
                pass
        return {"step": "inject_multi_pods", "status": "ok" if created > 0 else "failed",
                "created": created, "total": len(pods)}

    async def _resolve_existing_incidents(self, namespace: str):
        """Resolve any open incidents for this namespace so the scenario gets a fresh one."""
        try:
            from app.api.incidents import get_manager
            mgr = get_manager()
            for inc in mgr.list_incidents(status="open"):
                if inc.get("namespace") == namespace:
                    mgr.resolve_incident(inc["id"])
                    logger.info("Resolved existing incident %s for namespace %s", inc["id"][:8], namespace)
        except Exception as e:
            logger.warning("Failed to resolve existing incidents: %s", e)

    async def _inject_multi_signals(self, scenario: Scenario) -> dict:
        """Inject multiple signals to trigger correlation."""
        import httpx
        signals = scenario.inject_spec.get("signals", [])
        injected = 0
        for sig in signals:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "http://localhost:8099/api/v1/session/signals/inject", json=sig)
                    if resp.status_code == 200:
                        injected += 1
            except Exception:
                pass
        return {"step": "inject_multi_signals", "status": "ok", "injected": injected, "total": len(signals)}

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

    async def _wait_for_incident(self, namespace: str, timeout: int = 600) -> Optional[dict]:
        """Wait for a NEW open incident in this namespace."""
        from app.api.incidents import get_manager
        mgr = get_manager()
        start = time.monotonic()

        # Phase 1: wait for any open incident (up to 2/3 of timeout)
        found = None
        while time.monotonic() - start < timeout * 0.66:
            for inc in mgr.list_incidents(status="open"):
                if inc.get("namespace") == namespace:
                    found = inc
                    break
            if found:
                break
            await _async_sleep(5)

        if not found:
            return None

        # Phase 2: wait for RCA to be attached (remaining time)
        while time.monotonic() - start < timeout:
            inc = mgr.get_incident(found["id"])
            if inc and inc.get("rca_output"):
                return inc
            await _async_sleep(5)

        return found

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
