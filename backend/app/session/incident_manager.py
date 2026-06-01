"""Incident Manager — first-class incidents with append semantics and evidence chains.

Incidents are living documents that accumulate signals, classifications,
RCA outputs, and remediation options over time. Same namespace+signal_type
appends to existing open incident rather than creating duplicates.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("deepfield.incidents")

SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


class IncidentManager:
    def __init__(self):
        self._incidents: Dict[str, dict] = {}
        self._index: Dict[str, str] = {}

    def _key(self, namespace: str, cluster_id: str) -> str:
        return f"{cluster_id}:{namespace}"

    def process_signal(self, namespace: str, cluster_id: str, signal_type: str,
                       severity: str, signal_id: str, resource_name: str = "",
                       evidence: dict = None) -> dict:
        key = self._key(namespace, cluster_id)
        existing_id = self._index.get(key)

        if existing_id and existing_id in self._incidents:
            inc = self._incidents[existing_id]
            if inc["status"] == "open":
                inc["signal_count"] += 1
                inc["last_seen"] = datetime.now(timezone.utc).isoformat()
                if SEV_RANK.get(severity, 0) > SEV_RANK.get(inc["severity"], 0):
                    inc["severity"] = severity
                inc["evidence"].setdefault("signals", []).append({
                    "signal_id": signal_id, "type": signal_type,
                    "namespace": namespace, "resource": resource_name,
                    "severity": severity, "ts": datetime.now(timezone.utc).isoformat(),
                })
                inc["updated_at"] = datetime.now(timezone.utc).isoformat()
                return inc

        incident_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        inc = {
            "id": incident_id,
            "cluster_id": cluster_id,
            "namespace": namespace,
            "failure_class": None,
            "severity": severity,
            "status": "open",
            "signal_count": 1,
            "first_seen": now,
            "last_seen": now,
            "summary": None,
            "evidence": {
                "signals": [{
                    "signal_id": signal_id, "type": signal_type,
                    "namespace": namespace, "resource": resource_name,
                    "severity": severity, "ts": now,
                }],
                "findings": [],
                "classifications": [],
                "inferences": [],
                "remediations_suggested": [],
            },
            "classification": None,
            "remediation_options": [],
            "rca_output": None,
            "created_at": now,
            "updated_at": now,
        }
        self._incidents[incident_id] = inc
        self._index[key] = incident_id
        return inc

    def _find_open(self, namespace: str, cluster_id: str) -> Optional[dict]:
        key = self._key(namespace, cluster_id)
        inc_id = self._index.get(key)
        if inc_id and inc_id in self._incidents:
            inc = self._incidents[inc_id]
            if inc["status"] == "open":
                return inc
        return None

    def add_classification(self, namespace: str, cluster_id: str,
                           failure_class: str, confidence: float,
                           model: str = "") -> Optional[dict]:
        inc = self._find_open(namespace, cluster_id)
        if not inc:
            return None
        inc["failure_class"] = failure_class
        inc["classification"] = {
            "failure_class": failure_class,
            "confidence": confidence,
            "model": model,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        inc["evidence"]["classifications"].append(inc["classification"])
        inc["updated_at"] = datetime.now(timezone.utc).isoformat()
        return inc

    def add_inference(self, namespace: str, cluster_id: str,
                      task_type: str, model: str, output: str) -> Optional[dict]:
        inc = self._find_open(namespace, cluster_id)
        if not inc:
            return None
        inference_entry = {
            "type": task_type, "model": model,
            "output_summary": output[:2000] if output else "",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        inc["evidence"]["inferences"].append(inference_entry)
        if task_type == "root_cause_analysis":
            inc["rca_output"] = output
        inc["updated_at"] = datetime.now(timezone.utc).isoformat()
        return inc

    def add_remediation_option(self, namespace: str, cluster_id: str,
                               action: str, command: str = None,
                               risk: str = "medium", source: str = "llm") -> Optional[dict]:
        inc = self._find_open(namespace, cluster_id)
        if not inc:
            return None
        option = {"action": action, "command": command, "risk": risk, "source": source}
        inc["remediation_options"].append(option)
        inc["evidence"]["remediations_suggested"].append(option)
        inc["updated_at"] = datetime.now(timezone.utc).isoformat()
        return inc

    def resolve_incident(self, incident_id: str) -> dict:
        inc = self._incidents.get(incident_id)
        if not inc:
            return {"error": "not found"}
        inc["status"] = "resolved"
        inc["updated_at"] = datetime.now(timezone.utc).isoformat()
        key = self._key(inc["namespace"], inc["cluster_id"])
        if self._index.get(key) == incident_id:
            del self._index[key]
        return inc

    def list_incidents(self, status: str = None) -> List[dict]:
        incidents = list(self._incidents.values())
        if status:
            incidents = [i for i in incidents if i["status"] == status]
        return sorted(incidents, key=lambda i: (
            -SEV_RANK.get(i["severity"], 0),
            i.get("last_seen", ""),
        ), reverse=False)

    def get_incident(self, incident_id: str) -> Optional[dict]:
        return self._incidents.get(incident_id)
