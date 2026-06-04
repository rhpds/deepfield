"""Incident Manager — first-class incidents with append semantics and evidence chains.

Incidents are living documents that accumulate signals, classifications,
RCA outputs, and remediation options over time. Same namespace+signal_type
appends to existing open incident rather than creating duplicates.
"""

import json
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
        self._load_from_db()

    def _load_from_db(self):
        import os, json as _json, threading
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return

        results = []

        def _sync_load():
            try:
                import asyncio, asyncpg
                async def _do():
                    conn = await asyncpg.connect(db_url)
                    try:
                        return await conn.fetch(
                            "SELECT * FROM incidents WHERE status = 'open' ORDER BY last_seen DESC LIMIT 100"
                        )
                    finally:
                        await conn.close()
                loop = asyncio.new_event_loop()
                results.extend(loop.run_until_complete(_do()) or [])
                loop.close()
            except Exception as e:
                logger.debug("No incidents to load: %s", e)

        t = threading.Thread(target=_sync_load)
        t.start()
        t.join(timeout=10)

        for r in results:
            try:
                inc = {
                    "id": r["id"], "cluster_id": r["cluster_id"],
                    "namespace": r["namespace"], "failure_class": r["failure_class"],
                    "severity": r["severity"], "status": r["status"],
                    "signal_count": r["signal_count"] or 0,
                    "first_seen": r["first_seen"].isoformat() if r["first_seen"] else "",
                    "last_seen": r["last_seen"].isoformat() if r["last_seen"] else "",
                    "rca_output": r["rca_output"],
                    "evidence": _json.loads(r["evidence"]) if isinstance(r["evidence"], str) else (r["evidence"] or {}),
                    "classification": _json.loads(r["classification"]) if isinstance(r["classification"], str) else r["classification"],
                    "remediation_options": _json.loads(r["remediation_options"]) if isinstance(r["remediation_options"], str) else (r["remediation_options"] or []),
                    "summary": None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else "",
                }
                self._incidents[inc["id"]] = inc
                key = self._key(inc["namespace"], inc["cluster_id"])
                self._index[key] = inc["id"]
            except Exception:
                pass
        if results:
            logger.info("Loaded %d incidents from DB", len(results))

    def _persist(self, inc: dict):
        try:
            import json as _json
            from app.db import enqueue_write
            enqueue_write("incidents", {
                "id": inc["id"],
                "cluster_id": inc["cluster_id"],
                "namespace": inc["namespace"],
                "failure_class": inc.get("failure_class"),
                "severity": inc["severity"],
                "status": inc["status"],
                "signal_count": inc["signal_count"],
                "first_seen": inc.get("first_seen"),
                "last_seen": inc.get("last_seen"),
                "rca_output": inc.get("rca_output"),
                "evidence": _json.dumps(inc.get("evidence", {})),
                "classification": _json.dumps(inc.get("classification")) if inc.get("classification") else None,
                "remediation_options": _json.dumps(inc.get("remediation_options", [])),
            })
        except Exception as e:
            logger.debug("Incident persist failed: %s", e)

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
                signals = inc["evidence"].get("signals", [])
                sig_key = f"{signal_type}:{resource_name}"
                already_has = any(
                    f"{s.get('type', '')}:{s.get('resource', '')}" == sig_key
                    for s in signals
                )
                if not already_has and len(signals) < 30:
                    inc["signal_count"] += 1
                    signals.append({
                        "signal_id": signal_id, "type": signal_type,
                        "namespace": namespace, "resource": resource_name,
                        "severity": severity, "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    inc["evidence"]["signals"] = signals
                inc["last_seen"] = datetime.now(timezone.utc).isoformat()
                if SEV_RANK.get(severity, 0) > SEV_RANK.get(inc["severity"], 0):
                    inc["severity"] = severity
                inc["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._persist(inc)
                try:
                    if self.should_escalate_to_tarsy(inc):
                        self.escalate_to_tarsy(inc)
                except Exception:
                    pass
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
        self._persist(inc)
        try:
            if self.should_escalate_to_tarsy(inc):
                self.escalate_to_tarsy(inc)
        except Exception:
            pass
        return inc

    def should_escalate_to_tarsy(self, incident: dict) -> bool:
        """Check if incident should be escalated to TARSy for deep investigation."""
        if incident["evidence"].get("tarsy_escalated"):
            return False
        sev = incident.get("severity", "")
        if sev not in ("critical", "high"):
            return False
        findings = incident["evidence"].get("findings", [])
        has_cross_cluster = any(
            f.get("finding_type") == "cross_cluster_correlation" for f in findings
        )
        if has_cross_cluster:
            return True
        if sev == "critical" and incident.get("signal_count", 0) >= 5:
            return True
        return False

    def escalate_to_tarsy(self, incident: dict) -> None:
        """Build and publish a TARSy investigation request for this incident."""
        from app.integrations.kafka_publisher import publish_tarsy_request

        evidence_subset = {
            "signals": incident["evidence"].get("signals", []),
            "findings": incident["evidence"].get("findings", []),
            "classifications": incident["evidence"].get("classifications", []),
        }
        request = {
            "alert_type": "DeepFieldEscalation",
            "severity": incident["severity"],
            "originator_id": incident["id"],
            "data": json.dumps(evidence_subset),
            "mcp_override": {
                "servers": [{
                    "name": "kubernetes-server",
                    "tools": [
                        "get_pod_logs",
                        "get_events",
                        "describe_resource",
                        "list_resources",
                    ],
                }],
            },
        }
        try:
            publish_tarsy_request(request)
        except Exception as e:
            logger.debug("TARSy request publish failed: %s", e)
        incident["evidence"]["tarsy_escalated"] = True

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
        self._persist(inc)
        return inc

    def add_inference(self, namespace: str, cluster_id: str,
                      task_type: str, model: str, output: str) -> Optional[dict]:
        inc = self._find_open(namespace, cluster_id)
        if not inc:
            return None
        inferences = inc["evidence"].get("inferences", [])
        if len(inferences) >= 5:
            return inc
        inference_entry = {
            "type": task_type, "model": model,
            "output_summary": output[:2000] if output else "",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        inc["evidence"]["inferences"].append(inference_entry)
        if task_type in ("root_cause_analysis", "deep_root_cause_analysis", "cross_cluster_correlation"):
            inc["rca_output"] = output
        inc["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._persist(inc)
        return inc

    def add_remediation_option(self, namespace: str, cluster_id: str,
                               action: str, command: str = None,
                               risk: str = "medium", source: str = "llm") -> Optional[dict]:
        inc = self._find_open(namespace, cluster_id)
        if not inc:
            return None
        existing = inc["remediation_options"]
        if len(existing) >= 10:
            return inc
        action_normalized = action.strip().lower()
        if any(r.get("action", "").strip().lower() == action_normalized for r in existing):
            return inc
        option = {"action": action, "command": command, "risk": risk, "source": source}
        inc["remediation_options"].append(option)
        inc["evidence"]["remediations_suggested"].append(option)
        inc["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._persist(inc)
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
        self._persist(inc)
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
