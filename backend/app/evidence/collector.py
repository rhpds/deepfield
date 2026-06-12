"""Evidence bundle collector — gathers rich K8s context before LLM inference."""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

import httpx

logger = logging.getLogger("deepfield.evidence")

_bundle_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 60
_MAX_BUNDLE_BYTES = 100 * 1024
_MAX_LOG_LINES = 50
_K8S_TIMEOUT = 10.0


class EvidenceCollector:

    def __init__(self, collectors: list, enricher=None, incident_manager=None):
        self._collectors = collectors
        self._collector_map: Dict[str, object] = {}
        for c in collectors:
            self._collector_map[c.cluster_name] = c
        self._enricher = enricher
        self._incident_mgr = incident_manager

    def collect(self, finding) -> dict:
        namespaces = finding.namespaces or []
        ns = namespaces[0] if namespaces else ""
        cluster = self._resolve_cluster(finding)

        cache_key = f"{cluster}:{ns}"
        with _cache_lock:
            if cache_key in _bundle_cache:
                cached_bundle, cached_ts = _bundle_cache[cache_key]
                if time.monotonic() - cached_ts < _CACHE_TTL:
                    return {
                        "bundle_id": str(uuid4()),
                        "bundle": cached_bundle,
                        "finding_id": str(finding.finding_id),
                        "namespace": ns,
                        "cluster": cluster,
                    }

        bundle = {
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "namespaces": namespaces,
            "cluster": cluster,
            "signal_count": len(finding.signal_ids),
        }

        collector = self._collector_map.get(cluster)

        if collector and ns:
            bundle["events"] = self._collect_events(collector, ns)
            bundle["pod_statuses"] = self._collect_pod_statuses(collector, ns, finding)
            bundle["container_logs"] = self._collect_logs(collector, ns, finding)
            bundle["deployments"] = self._collect_deployment_state(collector, ns)

        if self._enricher and ns and cluster:
            try:
                metrics = self._enricher.enrich_namespace(cluster, ns)
                if metrics:
                    bundle["resource_metrics"] = metrics
            except Exception as e:
                logger.debug("Prometheus enrichment failed: %s", e)

        if self._incident_mgr and ns:
            bundle["prior_incidents"] = self._collect_incident_history(ns, cluster)

        bundle["collected_at"] = datetime.now(timezone.utc).isoformat()
        bundle = self._enforce_size_limit(bundle)

        with _cache_lock:
            _bundle_cache[cache_key] = (bundle, time.monotonic())
            if len(_bundle_cache) > 200:
                oldest = min(_bundle_cache, key=lambda k: _bundle_cache[k][1])
                del _bundle_cache[oldest]

        return {
            "bundle_id": str(uuid4()),
            "bundle": bundle,
            "finding_id": str(finding.finding_id),
            "namespace": ns,
            "cluster": cluster,
        }

    def _resolve_cluster(self, finding) -> str:
        for s in finding.evidence.get("signals", []):
            cluster = s.get("cluster", "")
            if cluster and len(cluster) > 3:
                return cluster
            src = s.get("evidence", {}).get("source", "")
            if ":" in src:
                name = src.split(":", 1)[-1]
                if name:
                    return name
        if self._collectors:
            return self._collectors[0].cluster_name
        return ""

    def _k8s_get(self, collector, path: str, params: dict = None) -> Optional[dict]:
        try:
            with httpx.Client(timeout=_K8S_TIMEOUT, verify=False) as client:
                resp = client.get(
                    f"{collector.api_url}{path}",
                    headers={"Authorization": f"Bearer {collector.token}"},
                    params=params or {},
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.debug("Evidence K8s GET %s failed: %s", path, str(e)[:100])
        return None

    def _collect_events(self, collector, namespace: str) -> list:
        data = self._k8s_get(
            collector, "/api/v1/events",
            params={"fieldSelector": f"involvedObject.namespace={namespace},type=Warning", "limit": "60"},
        )
        if not data:
            return []
        events = []
        for item in data.get("items", [])[:60]:
            involved = item.get("involvedObject", {})
            events.append({
                "kind": involved.get("kind", ""),
                "name": involved.get("name", ""),
                "reason": item.get("reason", ""),
                "message": item.get("message", "")[:300],
                "count": item.get("count", 1),
                "last_timestamp": item.get("lastTimestamp", ""),
            })
        return events

    def _collect_pod_statuses(self, collector, namespace: str, finding) -> list:
        pod_names = set()
        for s in finding.evidence.get("signals", []):
            if s.get("resource_kind") == "Pod" or s.get("signal_type", "").startswith("pod_"):
                name = s.get("resource_name", "")
                if name:
                    pod_names.add(name)

        if not pod_names:
            data = self._k8s_get(collector, f"/api/v1/namespaces/{namespace}/pods")
            if data:
                for item in data.get("items", [])[:20]:
                    phase = item.get("status", {}).get("phase", "")
                    if phase not in ("Running", "Succeeded"):
                        pod_names.add(item.get("metadata", {}).get("name", ""))

        pod_statuses = []
        for pod_name in list(pod_names)[:10]:
            data = self._k8s_get(collector, f"/api/v1/namespaces/{namespace}/pods/{pod_name}")
            if not data:
                continue
            status = data.get("status", {})
            pod_info = {
                "name": pod_name,
                "phase": status.get("phase", "Unknown"),
                "conditions": [
                    {"type": c.get("type"), "status": c.get("status"),
                     "reason": c.get("reason", ""), "message": c.get("message", "")[:200]}
                    for c in status.get("conditions", [])
                    if c.get("status") == "False"
                ],
                "containers": [],
            }
            for cs in status.get("containerStatuses", []) + status.get("initContainerStatuses", []):
                container = {
                    "name": cs.get("name", ""),
                    "ready": cs.get("ready", False),
                    "restart_count": cs.get("restartCount", 0),
                    "state": {},
                }
                state = cs.get("state", {})
                if "waiting" in state:
                    container["state"] = {"waiting": {
                        "reason": state["waiting"].get("reason", ""),
                        "message": state["waiting"].get("message", "")[:200],
                    }}
                elif "terminated" in state:
                    t = state["terminated"]
                    container["state"] = {"terminated": {
                        "exit_code": t.get("exitCode"),
                        "reason": t.get("reason", ""),
                        "message": t.get("message", "")[:200],
                    }}
                last = cs.get("lastState", {}).get("terminated", {})
                if last:
                    container["last_termination"] = {
                        "exit_code": last.get("exitCode"),
                        "reason": last.get("reason", ""),
                        "message": last.get("message", "")[:200],
                    }
                pod_info["containers"].append(container)
            pod_statuses.append(pod_info)
        return pod_statuses

    def _collect_logs(self, collector, namespace: str, finding) -> list:
        failing_pods = set()
        for s in finding.evidence.get("signals", []):
            sig_type = s.get("signal_type", "")
            if sig_type in ("pod_crashloop", "pod_imagepullbackoff") or "crash" in sig_type:
                name = s.get("resource_name", "")
                if name:
                    failing_pods.add(name)

        log_entries = []
        for pod_name in list(failing_pods)[:5]:
            for previous in [True, False]:
                try:
                    params = {"tailLines": str(_MAX_LOG_LINES), "timestamps": "true"}
                    if previous:
                        params["previous"] = "true"
                    with httpx.Client(timeout=_K8S_TIMEOUT, verify=False) as client:
                        resp = client.get(
                            f"{collector.api_url}/api/v1/namespaces/{namespace}/pods/{pod_name}/log",
                            headers={"Authorization": f"Bearer {collector.token}"},
                            params=params,
                        )
                        if resp.status_code == 200 and resp.text.strip():
                            log_entries.append({
                                "pod": pod_name,
                                "previous": previous,
                                "lines": resp.text.strip()[:5000],
                            })
                            break
                except Exception as e:
                    logger.debug("Log fetch failed for %s/%s: %s", namespace, pod_name, str(e)[:100])
        return log_entries

    def _collect_incident_history(self, namespace: str, cluster: str) -> list:
        try:
            all_incidents = self._incident_mgr.list_incidents()
            prior = []
            for inc in all_incidents:
                if inc.get("namespace") == namespace and inc.get("cluster_id") == cluster:
                    prior.append({
                        "id": inc.get("id", ""),
                        "severity": inc.get("severity", ""),
                        "status": inc.get("status", ""),
                        "failure_class": inc.get("failure_class", ""),
                        "signal_count": inc.get("signal_count", 0),
                        "first_seen": inc.get("first_seen", ""),
                        "last_seen": inc.get("last_seen", ""),
                    })
            return prior[:5]
        except Exception as e:
            logger.debug("Incident history lookup failed: %s", e)
            return []

    def _collect_deployment_state(self, collector, namespace: str) -> list:
        data = self._k8s_get(collector, f"/apis/apps/v1/namespaces/{namespace}/deployments")
        if not data:
            return []
        deployments = []
        for item in data.get("items", [])[:10]:
            meta = item.get("metadata", {})
            status = item.get("status", {})
            spec = item.get("spec", {})
            deployments.append({
                "name": meta.get("name", ""),
                "replicas": spec.get("replicas", 0),
                "ready_replicas": status.get("readyReplicas", 0),
                "available_replicas": status.get("availableReplicas", 0),
                "updated_replicas": status.get("updatedReplicas", 0),
                "conditions": [
                    {"type": c.get("type"), "status": c.get("status"),
                     "reason": c.get("reason", ""), "message": c.get("message", "")[:200]}
                    for c in status.get("conditions", [])
                    if c.get("status") == "False" or c.get("type") == "Progressing"
                ],
            })
        return deployments

    def _enforce_size_limit(self, bundle: dict) -> dict:
        serialized = json.dumps(bundle)
        if len(serialized) <= _MAX_BUNDLE_BYTES:
            return bundle
        for field in ["container_logs", "events", "pod_statuses", "deployments"]:
            if field in bundle and isinstance(bundle[field], list):
                while len(bundle[field]) > 1:
                    bundle[field].pop()
                    if len(json.dumps(bundle)) <= _MAX_BUNDLE_BYTES:
                        return bundle
        return bundle
