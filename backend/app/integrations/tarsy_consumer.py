"""TARSy result consumer — enriches DeepField incidents with TARSy investigation results."""

import json
import logging

logger = logging.getLogger("deepfield.tarsy")


def handle_tarsy_result(message: dict) -> None:
    """Process a TARSy investigation result to enrich the originating incident.

    Expects an EcosystemEvent envelope with:
      - payload.originator_id: the DeepField incident ID
      - payload.root_cause_analysis: RCA text from TARSy
      - payload.recommended_actions: list of action dicts
    """
    try:
        payload = message.get("payload", message)
        originator_id = payload.get("originator_id")
        if not originator_id:
            logger.debug("TARSy result missing originator_id, skipping")
            return

        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        incident = mgr.get_incident(originator_id)
        if not incident:
            logger.debug("No incident found for originator_id=%s", originator_id)
            return

        namespace = incident["namespace"]
        cluster_id = incident["cluster_id"]

        rca = payload.get("root_cause_analysis", "")
        if rca:
            mgr.add_inference(
                namespace=namespace,
                cluster_id=cluster_id,
                task_type="root_cause_analysis",
                model="tarsy",
                output=rca,
            )

        actions = payload.get("recommended_actions", [])
        for action in actions:
            if isinstance(action, dict):
                mgr.add_remediation_option(
                    namespace=namespace,
                    cluster_id=cluster_id,
                    action=action.get("action", ""),
                    command=action.get("command"),
                    risk=action.get("risk", "medium"),
                    source="tarsy",
                )
            elif isinstance(action, str):
                mgr.add_remediation_option(
                    namespace=namespace,
                    cluster_id=cluster_id,
                    action=action,
                    source="tarsy",
                )

        logger.debug("TARSy result processed for incident %s", originator_id)
    except Exception as e:
        logger.debug("TARSy result processing failed: %s", e)
