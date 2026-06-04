"""AlertManager collector — polls active alerts from OpenShift monitoring stack.

Lightweight, read-only, low-frequency (every 2 minutes).
Converts firing OCP alerts into DeepField signals for correlation
with K8s watch data.
"""

import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import uuid5, NAMESPACE_DNS

import httpx

from app.domain.models import RawSignal

logger = logging.getLogger(__name__)

ALERTMANAGER_URL = "https://alertmanager-main.openshift-monitoring.svc:9094"
POLL_INTERVAL = 120

ALERT_SEVERITY_MAP = {
    "critical": "alert_critical",
    "warning": "alert_warning",
    "info": "alert_info",
}

# Alerts that duplicate what K8s watch already catches — skip these
SKIP_ALERTS = {
    "KubePodCrashLooping",
    "KubePodNotReady",
    "KubeContainerWaiting",
    "KubeDaemonSetNotScheduled",
}


class AlertManagerCollector:
    def __init__(self, token: str = ""):
        self.token = token or os.getenv("ALERTMANAGER_TOKEN", "") or self._load_sa_token()
        self._cluster_id = uuid5(NAMESPACE_DNS, "deepfield:alertmanager:local")
        self._signal_buffer: deque = deque(maxlen=500)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seen_fingerprints: Set[str] = set()
        self._alert_counts: Dict[str, int] = {"total": 0, "critical": 0, "warning": 0, "info": 0}

    @staticmethod
    def _load_sa_token() -> str:
        try:
            with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as f:
                return f.read().strip()
        except Exception:
            return ""

    def start_watching(self):
        if not self.token:
            logger.info("AlertManager collector skipped — no auth token available")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="alertmanager-poller")
        self._thread.start()
        logger.info("AlertManager collector started (poll every %ds)", POLL_INTERVAL)

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

    def get_alert_counts(self) -> Dict[str, int]:
        return dict(self._alert_counts)

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self._fetch_alerts()
            except Exception as e:
                logger.warning("AlertManager poll error: %s", str(e)[:100])
            self._stop.wait(POLL_INTERVAL)

    def _fetch_alerts(self):
        try:
            with httpx.Client(timeout=15.0, verify=False) as client:
                resp = client.get(
                    f"{ALERTMANAGER_URL}/api/v2/alerts",
                    params={"active": "true", "silenced": "false", "inhibited": "false"},
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                if resp.status_code != 200:
                    logger.debug("AlertManager %d", resp.status_code)
                    return
                alerts = resp.json()
        except Exception as e:
            logger.debug("AlertManager fetch failed: %s", str(e)[:80])
            return

        self._alert_counts = {"total": 0, "critical": 0, "warning": 0, "info": 0}
        new_count = 0

        for alert in alerts:
            labels = alert.get("labels", {})
            alertname = labels.get("alertname", "")
            severity = labels.get("severity", "warning")
            namespace = labels.get("namespace", "cluster")
            fingerprint = alert.get("fingerprint", "")

            if alertname in SKIP_ALERTS:
                continue

            sev_key = severity if severity in self._alert_counts else "warning"
            self._alert_counts["total"] += 1
            self._alert_counts[sev_key] = self._alert_counts.get(sev_key, 0) + 1

            if fingerprint in self._seen_fingerprints:
                continue
            self._seen_fingerprints.add(fingerprint)

            if len(self._seen_fingerprints) > 5000:
                self._seen_fingerprints = set(list(self._seen_fingerprints)[-2500:])

            signal_type = ALERT_SEVERITY_MAP.get(severity, "alert_warning")
            annotations = alert.get("annotations", {})

            sig = RawSignal(
                signal_id=uuid5(NAMESPACE_DNS, f"alert:{fingerprint}"),
                cluster_id=self._cluster_id,
                namespace=namespace,
                resource_kind="Alert",
                resource_name=alertname,
                source="alertmanager:local",
                signal_type=signal_type,
                raw_payload={
                    "alertname": alertname,
                    "severity": severity,
                    "summary": annotations.get("summary", "")[:300],
                    "description": annotations.get("description", "")[:500],
                    "message": annotations.get("message", "")[:300],
                    "starts_at": alert.get("startsAt", ""),
                    "labels": {k: v for k, v in labels.items()
                               if k not in ("__name__", "prometheus", "endpoint", "job", "service")},
                },
                timestamp=datetime.now(timezone.utc),
            )
            self._signal_buffer.append(sig)
            new_count += 1

        if new_count > 0:
            logger.info("AlertManager: %d active alerts, %d new signals", len(alerts), new_count)
