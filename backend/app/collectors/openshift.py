"""Read-only OpenShift collector — watches live cluster events via K8s watch API.

Uses persistent HTTP streaming connections for real-time events.
Initial scan gets current state, then watches stream changes as they happen.

Rules:
- READ-ONLY. Watch/Get only. Never apply/delete/patch/create.
- No secret values. Only metadata.
"""

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Dict, List, Optional, Tuple
from uuid import uuid5, NAMESPACE_DNS

import httpx

from app.domain.models import ClusterRef, RawSignal

logger = logging.getLogger(__name__)


class OpenShiftCollector:
    def __init__(
        self,
        cluster_name: str,
        api_url: str,
        token: str = "",
        include_namespaces: Optional[List[str]] = None,
        exclude_namespaces: Optional[List[str]] = None,
    ):
        self.cluster_name = cluster_name
        self.api_url = api_url
        self.token = token
        self.include_ns = include_namespaces or ["*"]
        self.exclude_ns = exclude_namespaces or ["openshift-*", "kube-*"]
        self._cluster_id = uuid5(NAMESPACE_DNS, f"deepfield:cluster:{cluster_name}")
        self._read_only = True
        self._signal_buffer: deque = deque(maxlen=5000)
        self._watchers: List[threading.Thread] = []
        self._stop = threading.Event()
        self._initial_scan_done = False

    @property
    def read_only(self) -> bool:
        return self._read_only

    def _ns_allowed(self, ns: str) -> bool:
        if any(fnmatch(ns, pat) for pat in self.exclude_ns):
            return False
        return any(fnmatch(ns, pat) for pat in self.include_ns)

    def _make_signal(self, namespace: str, kind: str, name: str,
                     signal_type: str, payload: dict) -> RawSignal:
        sig_key = f"{self.cluster_name}:{namespace}:{kind}:{name}:{signal_type}:{datetime.now().isoformat()}"
        return RawSignal(
            signal_id=uuid5(NAMESPACE_DNS, sig_key),
            cluster_id=self._cluster_id,
            namespace=namespace,
            resource_kind=kind,
            resource_name=name,
            source=f"live:{self.cluster_name}",
            signal_type=signal_type,
            raw_payload=payload,
            timestamp=datetime.now(timezone.utc),
        )

    def _buffer_signal(self, signal: RawSignal):
        """Buffer signal locally AND publish to Kafka (Phase 1 dual-write)."""
        self._signal_buffer.append(signal)
        try:
            from app.integrations.kafka_publisher import publish_raw_signal
            publish_raw_signal({
                "signal_id": str(signal.signal_id),
                "cluster_id": str(signal.cluster_id),
                "namespace": signal.namespace,
                "resource_kind": signal.resource_kind,
                "resource_name": signal.resource_name,
                "source": signal.source,
                "signal_type": signal.signal_type,
                "raw_payload": signal.raw_payload,
                "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
            })
        except Exception:
            pass

    def start_watching(self):
        """Start watch threads for each resource type."""
        self._stop.clear()
        t = threading.Thread(target=self._initial_scan, daemon=True)
        t.start()
        self._watchers.append(t)

        for resource, path in [
            ("pods", "/api/v1/pods"),
            ("events", "/api/v1/events"),
            ("nodes", "/api/v1/nodes"),
        ]:
            t = threading.Thread(target=self._watch_resource, args=(resource, path), daemon=True)
            t.start()
            self._watchers.append(t)

    def stop(self):
        self._stop.set()

    def drain_signals(self) -> List[RawSignal]:
        signals = []
        while self._signal_buffer:
            try:
                signals.append(self._signal_buffer.popleft())
            except IndexError:
                break
        return signals

    def collect(self) -> Tuple[List[ClusterRef], List[RawSignal]]:
        cluster = ClusterRef(
            cluster_id=self._cluster_id,
            display_name=self.cluster_name,
            environment="live",
            source_type="openshift",
            api_url=self.api_url,
        )
        if not self._initial_scan_done:
            self._initial_scan()
        signals = self.drain_signals()
        return [cluster], signals

    def _k8s_get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        try:
            with httpx.Client(timeout=10.0, verify=False) as client:
                resp = client.get(
                    f"{self.api_url}{path}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    params=params or {},
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("K8s GET %s: %d", path, resp.status_code)
        except Exception as e:
            logger.warning("K8s GET %s: %s", path, str(e)[:100])
        return None

    def _initial_scan(self):
        logger.info("Initial scan of %s...", self.cluster_name)
        data = self._k8s_get("/api/v1/pods")
        if data:
            for item in data.get("items", []):
                self._process_pod(item)
        data = self._k8s_get("/api/v1/nodes")
        if data:
            for item in data.get("items", []):
                self._process_node(item)
        data = self._k8s_get("/api/v1/events", {"fieldSelector": "type=Warning"})
        if data:
            for item in data.get("items", []):
                self._process_event(item)
        self._initial_scan_done = True
        logger.info("Initial scan: %d signals from %s", len(self._signal_buffer), self.cluster_name)

    def rescan(self):
        """Periodic re-scan — captures current state for pods stuck in stable bad states."""
        data = self._k8s_get("/api/v1/pods")
        if data:
            for item in data.get("items", []):
                self._process_pod(item)
        data = self._k8s_get("/api/v1/events", {"fieldSelector": "type=Warning"})
        if data:
            for item in data.get("items", []):
                self._process_event(item)

    def _watch_resource(self, resource: str, path: str):
        while not self._stop.is_set():
            try:
                params = {"watch": "true", "timeoutSeconds": "300"}
                if resource == "events":
                    params["fieldSelector"] = "type=Warning"
                with httpx.Client(timeout=None, verify=False) as client:
                    with client.stream("GET", f"{self.api_url}{path}",
                        headers={"Authorization": f"Bearer {self.token}"}, params=params) as resp:
                        if resp.status_code != 200:
                            logger.warning("Watch %s/%s: %d", self.cluster_name, resource, resp.status_code)
                            self._stop.wait(10)
                            continue
                        for line in resp.iter_lines():
                            if self._stop.is_set():
                                break
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                                obj = event.get("object", {})
                                if resource == "pods":
                                    self._process_pod(obj)
                                elif resource == "nodes":
                                    self._process_node(obj)
                                elif resource == "events":
                                    self._process_event(obj)
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                if not self._stop.is_set():
                    logger.warning("Watch %s/%s error: %s", self.cluster_name, resource, str(e)[:100])
                    self._stop.wait(5)

    def _pod_context(self, item: dict) -> dict:
        """Extract owner, labels, node, and resource context from a pod."""
        meta = item.get("metadata", {})
        spec = item.get("spec", {})
        ctx = {}
        labels = meta.get("labels", {})
        if labels.get("app"):
            ctx["app"] = labels["app"]
        elif labels.get("app.kubernetes.io/name"):
            ctx["app"] = labels["app.kubernetes.io/name"]
        owners = meta.get("ownerReferences", [])
        if owners:
            ctx["owner"] = f"{owners[0].get('kind', '')}/{owners[0].get('name', '')}"
        if spec.get("nodeName"):
            ctx["node"] = spec["nodeName"]
        return ctx

    def _container_detail(self, cs: dict) -> dict:
        """Extract crash/exit details from a container status."""
        detail = {"container": cs.get("name", ""), "image": cs.get("image", "")}
        last = cs.get("lastState", {}).get("terminated", {})
        if last:
            if last.get("exitCode") is not None:
                detail["exit_code"] = last["exitCode"]
            if last.get("reason"):
                detail["exit_reason"] = last["reason"]
            if last.get("message"):
                detail["exit_message"] = last["message"][:200]
        return detail

    def _process_pod(self, item: dict, event_type: str = ""):
        ns = item.get("metadata", {}).get("namespace", "")
        if not self._ns_allowed(ns):
            return
        name = item.get("metadata", {}).get("name", "")
        status = item.get("status", {})
        phase = status.get("phase", "Unknown")
        pod_ctx = self._pod_context(item)

        if phase == "Running":
            for cs in status.get("containerStatuses", []):
                restarts = cs.get("restartCount", 0)
                waiting = cs.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")
                if restarts > 3 or reason == "CrashLoopBackOff":
                    detail = self._container_detail(cs)
                    self._buffer_signal(self._make_signal(ns, "Pod", name, "pod_crashloop",
                        {"restartCount": restarts, "reason": "CrashLoopBackOff", **detail, **pod_ctx}))
                    return
                elif reason == "ImagePullBackOff":
                    self._buffer_signal(self._make_signal(ns, "Pod", name, "pod_imagepullbackoff",
                        {"reason": reason, "image": cs.get("image", ""), **pod_ctx}))
                    return
            self._buffer_signal(self._make_signal(ns, "Pod", name, "pod_running", {}))
        elif phase == "Pending":
            conditions = status.get("conditions", [])
            sched = next((c for c in conditions if c.get("type") == "PodScheduled" and c.get("status") == "False"), None)
            payload = {"phase": phase, **pod_ctx}
            if sched:
                payload["schedule_reason"] = sched.get("reason", "")
                payload["schedule_message"] = sched.get("message", "")[:200]
            self._buffer_signal(self._make_signal(ns, "Pod", name, "pod_pending", payload))
        elif phase == "Failed":
            self._buffer_signal(self._make_signal(ns, "Pod", name, "pod_crashloop",
                {"phase": phase, "reason": status.get("reason", ""), "message": status.get("message", "")[:200], **pod_ctx}))
        else:
            for cs in status.get("containerStatuses", []) + status.get("initContainerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")
                if reason == "ImagePullBackOff":
                    self._buffer_signal(self._make_signal(ns, "Pod", name, "pod_imagepullbackoff",
                        {"reason": reason, "image": cs.get("image", ""), **pod_ctx}))
                    return
                elif reason in ("CrashLoopBackOff", "Error", "CreateContainerError"):
                    detail = self._container_detail(cs)
                    self._buffer_signal(self._make_signal(ns, "Pod", name, "pod_crashloop",
                        {"reason": reason, **detail, **pod_ctx}))
                    return

    def _process_node(self, item: dict, event_type: str = ""):
        name = item.get("metadata", {}).get("name", "")
        conditions = {c["type"]: c for c in item.get("status", {}).get("conditions", [])}
        ready = conditions.get("Ready", {})
        if ready.get("status") == "True":
            self._buffer_signal(self._make_signal("", "Node", name, "node_ready", {}))
        else:
            self._buffer_signal(self._make_signal("", "Node", name, "node_pressure", {"condition": "NotReady"}))
        for ptype in ("MemoryPressure", "DiskPressure", "PIDPressure"):
            cond = conditions.get(ptype, {})
            if cond.get("status") == "True":
                self._buffer_signal(self._make_signal("", "Node", name, "node_pressure", {"condition": ptype}))

    def _process_event(self, item: dict):
        ns = item.get("metadata", {}).get("namespace", "")
        if not self._ns_allowed(ns):
            return
        involved = item.get("involvedObject", {})
        kind = involved.get("kind", "Unknown")
        name = involved.get("name", "unknown")
        reason = item.get("reason", "")
        message = item.get("message", "")[:200]
        signal_type = f"event_{reason.lower()}" if reason else "event_unknown"
        if "e2e" in ns:
            logger.warning("E2E EVENT: ns=%s kind=%s name=%s reason=%s type=%s", ns, kind, name, reason, signal_type)
        self._buffer_signal(self._make_signal(ns, kind, name, signal_type,
            {"reason": reason, "message": message, "count": item.get("count", 1)}))
