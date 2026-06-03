"""Tests for TARSy escalation trigger and result consumer."""

import json
import pytest
from unittest.mock import patch, MagicMock


class TestShouldEscalateToTarsy:
    def test_critical_cross_cluster_escalates(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="critical",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc["evidence"]["findings"].append({
            "finding_type": "cross_cluster_correlation",
            "severity": "critical",
        })
        assert mgr.should_escalate_to_tarsy(inc) is True

    def test_high_cross_cluster_escalates(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc["evidence"]["findings"].append({
            "finding_type": "cross_cluster_correlation",
            "severity": "high",
        })
        assert mgr.should_escalate_to_tarsy(inc) is True

    @patch("app.integrations.kafka_publisher.publish_tarsy_request")
    def test_critical_with_five_signals_escalates(self, mock_publish):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="critical",
            signal_id="sig-001", resource_name="pod-a",
        )
        for i in range(2, 6):
            mgr.process_signal(
                namespace="stargate", cluster_id="infra01",
                signal_type="pod_crashloop", severity="critical",
                signal_id=f"sig-{i:03d}", resource_name=f"pod-{i}",
            )
        inc = mgr.get_incident(inc["id"])
        assert inc["signal_count"] >= 5
        assert inc["evidence"]["tarsy_escalated"] is True
        assert mock_publish.called

    def test_low_severity_does_not_escalate(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="event_backoff", severity="low",
            signal_id="sig-001", resource_name="pod-a",
        )
        assert mgr.should_escalate_to_tarsy(inc) is False

    def test_medium_severity_does_not_escalate(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="event_backoff", severity="medium",
            signal_id="sig-001", resource_name="pod-a",
        )
        assert mgr.should_escalate_to_tarsy(inc) is False

    def test_already_escalated_does_not_re_escalate(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="critical",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc["evidence"]["findings"].append({
            "finding_type": "cross_cluster_correlation",
            "severity": "critical",
        })
        inc["evidence"]["tarsy_escalated"] = True
        assert mgr.should_escalate_to_tarsy(inc) is False

    def test_high_without_cross_cluster_or_enough_signals_does_not_escalate(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        assert mgr.should_escalate_to_tarsy(inc) is False


class TestEscalateToTarsy:
    @patch("app.integrations.kafka_publisher.publish_tarsy_request")
    def test_builds_correct_request_payload(self, mock_publish):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="critical",
            signal_id="sig-001", resource_name="pod-a",
        )
        mgr.escalate_to_tarsy(inc)

        mock_publish.assert_called_once()
        request = mock_publish.call_args[0][0]
        assert request["alert_type"] == "DeepFieldEscalation"
        assert request["severity"] == "critical"
        assert request["originator_id"] == inc["id"]
        data = json.loads(request["data"])
        assert "signals" in data
        assert "findings" in data
        assert "classifications" in data
        assert request["mcp_override"]["servers"][0]["name"] == "kubernetes-server"
        assert inc["evidence"]["tarsy_escalated"] is True

    @patch("app.integrations.kafka_publisher.publish_tarsy_request", side_effect=Exception("kafka down"))
    def test_marks_escalated_even_on_publish_failure(self, mock_publish):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="critical",
            signal_id="sig-001", resource_name="pod-a",
        )
        mgr.escalate_to_tarsy(inc)
        assert inc["evidence"]["tarsy_escalated"] is True


class TestHandleTarsyResult:
    def test_enriches_incident_with_rca_and_actions(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="critical",
            signal_id="sig-001", resource_name="pod-a",
        )

        with patch("app.session.incident_manager.IncidentManager", return_value=mgr):
            from app.integrations.tarsy_consumer import handle_tarsy_result

            result_message = {
                "payload": {
                    "originator_id": inc["id"],
                    "root_cause_analysis": "Memory leak in stargate-api container",
                    "recommended_actions": [
                        {"action": "Increase memory limit to 2Gi", "command": "oc set resources ...", "risk": "low"},
                        {"action": "Restart pod", "command": "oc delete pod ...", "risk": "medium"},
                    ],
                },
            }
            handle_tarsy_result(result_message)

        updated = mgr.get_incident(inc["id"])
        assert updated["rca_output"] is not None
        assert "Memory leak" in updated["rca_output"]
        assert len(updated["remediation_options"]) == 2
        assert updated["remediation_options"][0]["source"] == "tarsy"
        assert updated["remediation_options"][1]["action"] == "Restart pod"

    def test_handles_missing_originator_id(self):
        from app.integrations.tarsy_consumer import handle_tarsy_result
        # Should not raise
        handle_tarsy_result({"payload": {}})

    def test_handles_unknown_originator_id(self):
        from app.integrations.tarsy_consumer import handle_tarsy_result
        # Should not raise
        with patch("app.session.incident_manager.IncidentManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.get_incident.return_value = None
            mock_cls.return_value = mock_mgr
            handle_tarsy_result({"payload": {"originator_id": "nonexistent-id"}})

    def test_handles_string_actions(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="critical",
            signal_id="sig-001", resource_name="pod-a",
        )

        with patch("app.session.incident_manager.IncidentManager", return_value=mgr):
            from app.integrations.tarsy_consumer import handle_tarsy_result

            result_message = {
                "payload": {
                    "originator_id": inc["id"],
                    "root_cause_analysis": "OOM",
                    "recommended_actions": ["Scale up replicas"],
                },
            }
            handle_tarsy_result(result_message)

        updated = mgr.get_incident(inc["id"])
        assert len(updated["remediation_options"]) == 1
        assert updated["remediation_options"][0]["action"] == "Scale up replicas"
        assert updated["remediation_options"][0]["source"] == "tarsy"
