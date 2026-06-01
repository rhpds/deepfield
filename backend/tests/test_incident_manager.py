"""TDD tests for the incident manager — rich evidence-driven incidents."""

import pytest
from datetime import datetime, timezone


class TestIncidentCreation:
    def test_new_signal_creates_incident(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        incident = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="stargate-api-xyz",
        )
        assert incident is not None
        assert incident["namespace"] == "stargate"
        assert incident["severity"] == "high"
        assert incident["status"] == "open"
        assert incident["signal_count"] == 1

    def test_second_signal_appends_to_existing(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc1 = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc2 = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-002", resource_name="pod-b",
        )
        assert inc1["id"] == inc2["id"]
        assert inc2["signal_count"] == 2

    def test_different_namespace_creates_new_incident(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc1 = mgr.process_signal(
            namespace="stargate", cluster_id="infra01",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc2 = mgr.process_signal(
            namespace="deepfield", cluster_id="infra01",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-002", resource_name="pod-b",
        )
        assert inc1["id"] != inc2["id"]

    def test_severity_upgrades(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        mgr.process_signal(
            namespace="test", cluster_id="c1",
            signal_type="event_backoff", severity="medium",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc = mgr.process_signal(
            namespace="test", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-002", resource_name="pod-a",
        )
        assert inc["severity"] == "high"


class TestEvidenceChain:
    def test_signals_accumulated_in_evidence(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc = mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="oom_killed", severity="critical",
            signal_id="sig-002", resource_name="pod-a",
        )
        evidence = inc["evidence"]
        assert len(evidence.get("signals", [])) == 2

    def test_classification_attached(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc = mgr.add_classification(
            namespace="ns", cluster_id="c1",
            failure_class="pods_crashlooping", confidence=0.95,
            model="granite_tiny",
        )
        assert inc is not None
        assert inc["failure_class"] == "pods_crashlooping"
        assert inc["classification"]["confidence"] == 0.95

    def test_rca_attached(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc = mgr.add_inference(
            namespace="ns", cluster_id="c1",
            task_type="root_cause_analysis", model="deepseek",
            output="OOM kill due to memory limit exceeded on pod-a",
        )
        assert inc is not None
        assert "OOM" in inc["rca_output"]

    def test_remediation_options_attached(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        inc = mgr.add_remediation_option(
            namespace="ns", cluster_id="c1",
            action="Increase memory limit", command="oc set resources ...",
            risk="low", source="rca",
        )
        assert inc is not None
        assert len(inc["remediation_options"]) >= 1
        assert inc["remediation_options"][0]["action"] == "Increase memory limit"


class TestIncidentLifecycle:
    def test_resolve_incident(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc = mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        resolved = mgr.resolve_incident(inc["id"])
        assert resolved["status"] == "resolved"

    def test_new_signal_after_resolve_creates_new_incident(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        inc1 = mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-001", resource_name="pod-a",
        )
        mgr.resolve_incident(inc1["id"])
        inc2 = mgr.process_signal(
            namespace="ns", cluster_id="c1",
            signal_type="pod_crashloop", severity="high",
            signal_id="sig-002", resource_name="pod-a",
        )
        assert inc1["id"] != inc2["id"]

    def test_list_incidents(self):
        from app.session.incident_manager import IncidentManager
        mgr = IncidentManager()
        mgr.process_signal(namespace="ns-a", cluster_id="c1", signal_type="x", severity="high", signal_id="1", resource_name="p")
        mgr.process_signal(namespace="ns-b", cluster_id="c1", signal_type="y", severity="medium", signal_id="2", resource_name="q")
        incidents = mgr.list_incidents()
        assert len(incidents) == 2
