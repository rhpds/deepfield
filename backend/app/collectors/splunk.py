"""Splunk Cloud collector — polls fired alerts and saved search results via REST API.

Stage 1: Fired alerts only (GET /services/alerts/fired_alerts).
Stage 2: Saved search dispatch + result ingestion.
Stage 3: Ad-hoc SPL query execution.

Read-only. Never modifies Splunk state.
"""

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import uuid5, NAMESPACE_DNS

import httpx

from app.domain.models import RawSignal

logger = logging.getLogger(__name__)

SPLUNK_SEVERITY_MAP = {
    "1": "splunk_info_alert",
    "2": "splunk_low_alert",
    "3": "splunk_medium_alert",
    "4": "splunk_high_alert",
    "5": "splunk_critical_alert",
    "info": "splunk_info_alert",
    "low": "splunk_low_alert",
    "medium": "splunk_medium_alert",
    "high": "splunk_high_alert",
    "critical": "splunk_critical_alert",
}


class SplunkCollector:
    def __init__(
        self,
        name: str,
        base_url: str,
        token: str = "",
        username: str = "",
        password: str = "",
        poll_interval: int = 60,
        indexes: Optional[List[str]] = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.username = username
        self.password = password
        self.poll_interval = poll_interval
        self.indexes = indexes or ["*"]
        self._cluster_id = uuid5(NAMESPACE_DNS, f"deepfield:splunk:{name}")
        self._signal_buffer: deque = deque(maxlen=2000)
        self._stop = threading.Event()
        self._watchers: List[threading.Thread] = []
        self._seen_alerts: Set[str] = set()
        self._alert_counts: Dict[str, int] = {
            "total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0,
        }
        self._alert_lock = threading.Lock()

    def _auth_kwargs(self) -> dict:
        if self.token:
            return {"headers": {"Authorization": f"Bearer {self.token}"}}
        if self.username and self.password:
            return {"auth": (self.username, self.password)}
        return {}

    def _api_get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        try:
            with httpx.Client(timeout=30.0, verify=False) as client:
                resp = client.get(
                    f"{self.base_url}{path}",
                    **self._auth_kwargs(),
                    params={**(params or {}), "output_mode": "json"},
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("Splunk GET %s: %d %s", path, resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("Splunk GET %s: %s", path, str(e)[:100])
        return None

    def start_watching(self):
        self._stop.clear()
        t = threading.Thread(target=self._poll_alerts, daemon=True, name=f"splunk-{self.name}")
        t.start()
        self._watchers.append(t)
        logger.info("SplunkCollector started for %s (%s)", self.name, self.base_url)

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
        with self._alert_lock:
            return dict(self._alert_counts)

    def rescan(self):
        self._poll_fired_alerts()

    def _make_signal(self, app: str, search_name: str,
                     signal_type: str, payload: dict) -> RawSignal:
        sig_key = f"splunk:{self.name}:{app}:{search_name}:{signal_type}:{datetime.now().isoformat()}"
        return RawSignal(
            signal_id=uuid5(NAMESPACE_DNS, sig_key),
            cluster_id=self._cluster_id,
            namespace=app,
            resource_kind="SplunkAlert",
            resource_name=search_name,
            source=f"splunk:{self.name}",
            signal_type=signal_type,
            raw_payload=payload,
            timestamp=datetime.now(timezone.utc),
        )

    def _poll_alerts(self):
        while not self._stop.is_set():
            self._poll_fired_alerts()
            self._stop.wait(self.poll_interval)

    def _poll_fired_alerts(self):
        data = self._api_get("/services/alerts/fired_alerts")
        if not data:
            return

        entries = data.get("entry", [])
        with self._alert_lock:
            self._alert_counts = {
                "total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0,
            }

        for entry in entries:
            try:
                content = entry.get("content", {})
                alert_name = entry.get("name", "unknown")
                triggered_count = content.get("triggered_alert_count", 0)

                if triggered_count == 0:
                    continue

                severity_num = str(content.get("alert.severity", "3"))
                signal_type = SPLUNK_SEVERITY_MAP.get(severity_num, "splunk_medium_alert")

                app = content.get("eai:acl", {}).get("app", "search")
                trigger_key = f"{alert_name}:{content.get('alert.expires', '')}"

                if trigger_key in self._seen_alerts:
                    continue
                self._seen_alerts.add(trigger_key)

                if len(self._seen_alerts) > 10000:
                    self._seen_alerts = set(list(self._seen_alerts)[-5000:])

                payload = {
                    "search_name": alert_name,
                    "triggered_count": triggered_count,
                    "severity": severity_num,
                    "app": app,
                    "search_query": content.get("search", "")[:500],
                    "cron_schedule": content.get("cron_schedule", ""),
                    "description": content.get("description", "")[:200],
                }

                sig = self._make_signal(app, alert_name, signal_type, payload)
                self._signal_buffer.append(sig)

                sev_label = signal_type.replace("splunk_", "").replace("_alert", "")
                with self._alert_lock:
                    self._alert_counts["total"] += 1
                    if sev_label in self._alert_counts:
                        self._alert_counts[sev_label] += 1

            except Exception as e:
                logger.warning("Splunk alert parse error: %s", str(e)[:100])

        logger.info("Splunk %s: polled %d alerts, %d new signals",
                     self.name, len(entries), self._alert_counts["total"])
