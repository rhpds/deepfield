"""Outbound event publisher — pushes remediation suggestions to Launchpad + audit to dashboard."""

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

LAUNCHPAD_API_URL = os.environ.get("LAUNCHPAD_API_URL")
LAUNCHPAD_API_KEY = os.environ.get("LAUNCHPAD_API_KEY")
DASHBOARD_AUDIT_URL = os.environ.get("DASHBOARD_AUDIT_URL")
STARGATE_API_URL = os.environ.get("STARGATE_API_URL", "")
STARGATE_API_KEY = os.environ.get("STARGATE_API_KEY", "")
SSL_VERIFY = os.environ.get("INTEGRATION_SSL_VERIFY", "true").lower() != "false"


async def suggest_remediation(session_id: str, action: str, reason: str, evidence: dict):
    """Push remediation suggestion to Launchpad. Fails silently if not configured."""
    if not LAUNCHPAD_API_URL:
        return
    try:
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=5.0) as client:
            headers = {"X-API-Key": LAUNCHPAD_API_KEY} if LAUNCHPAD_API_KEY else {}
            await client.post(
                f"{LAUNCHPAD_API_URL}/callbacks/remediation",
                json={
                    "session_id": session_id,
                    "action": action,
                    "reason": reason,
                    "evidence": evidence,
                },
                headers=headers,
            )
    except Exception as e:
        logger.debug("DeepField -> Launchpad remediation push failed (non-critical): %s", e)

    await _push_audit({
        "source": "deepfield",
        "event_type": "remediation_suggestion",
        "event_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "action": action,
        "reason": reason,
    })


async def _push_audit(event: dict):
    """Push to dashboard central audit trail. Fails silently."""
    if not DASHBOARD_AUDIT_URL:
        return
    try:
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=5.0) as client:
            await client.post(f"{DASHBOARD_AUDIT_URL}/api/audit/append", json=event)
    except Exception as e:
        logger.debug("Audit push failed (non-critical): %s", e)


def push_incident_to_stargate(incident: dict) -> bool:
    """Push an enriched incident to StarGate's approval queue.

    Read-only integration -- incidents land as pending proposals
    for human review. No auto-remediation.
    """
    if not STARGATE_API_URL:
        return False

    try:
        payload = {
            "source": "deepfield",
            "incident_id": str(incident.get("incident_id", "")),
            "namespace": incident.get("namespace", ""),
            "cluster": incident.get("cluster", ""),
            "lab_code": incident.get("lab_code"),
            "failure_class": incident.get("failure_class"),
            "severity": incident.get("severity", "medium"),
            "confidence": float(incident.get("confidence", 0.5)),
            "rca_output": incident.get("rca_output"),
            "correlated_signals": incident.get("correlated_signals", [])[:10],
            "remediation_options": incident.get("remediation_options", [])[:10],
            "evidence_chain": incident.get("evidence_chain", [])[:10],
            "signal_count": int(incident.get("signal_count", 0)),
        }

        headers = {"Content-Type": "application/json"}
        if STARGATE_API_KEY:
            headers["X-API-Key"] = STARGATE_API_KEY

        endpoint = f"{STARGATE_API_URL.rstrip('/')}/integration/deepfield-incident"
        resp = httpx.post(endpoint, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info("Pushed incident %s to StarGate (status=%s)", incident.get("incident_id"), resp.status_code)
        return True
    except Exception as e:
        logger.warning("Failed to push incident to StarGate: %s", e)
        return False
