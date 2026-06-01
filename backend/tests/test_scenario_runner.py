"""TDD tests for the synthetic scenario runner."""

import pytest

ECOSYSTEM = {"deepfield", "stargate", "partner-ai-launchpad", "platform-dashboard", "intel-rh-demo"}


class TestScenarioDefinitions:
    def test_all_scenarios_in_ecosystem_namespaces(self):
        from app.testing.scenario_runner import SCENARIOS
        for sid, scenario in SCENARIOS.items():
            assert scenario.namespace in ECOSYSTEM, f"Scenario {sid} uses non-ecosystem namespace {scenario.namespace}"

    def test_at_least_4_scenarios(self):
        from app.testing.scenario_runner import SCENARIOS
        assert len(SCENARIOS) >= 4

    def test_scenario_has_required_fields(self):
        from app.testing.scenario_runner import SCENARIOS
        for sid, s in SCENARIOS.items():
            assert s.id, f"{sid} missing id"
            assert s.name, f"{sid} missing name"
            assert s.namespace, f"{sid} missing namespace"
            assert s.inject_type, f"{sid} missing inject_type"
            assert s.expected_classification, f"{sid} missing expected_classification"

    def test_cleanup_resources_defined(self):
        from app.testing.scenario_runner import SCENARIOS
        for sid, s in SCENARIOS.items():
            if s.inject_type != "synthetic_signal":
                assert len(s.cleanup_resources) > 0, f"{sid} creates resources but has no cleanup"


class TestNamespaceSafety:
    def test_reject_non_ecosystem_namespace(self):
        from app.testing.scenario_runner import ScenarioRunner
        runner = ScenarioRunner(cluster_api_url="http://fake", token="fake")
        with pytest.raises((AssertionError, ValueError)):
            runner.validate_namespace("kube-system")

    def test_accept_ecosystem_namespace(self):
        from app.testing.scenario_runner import ScenarioRunner
        runner = ScenarioRunner(cluster_api_url="http://fake", token="fake")
        runner.validate_namespace("deepfield")
        runner.validate_namespace("stargate")
        runner.validate_namespace("platform-dashboard")

    def test_reject_empty_namespace(self):
        from app.testing.scenario_runner import ScenarioRunner
        runner = ScenarioRunner(cluster_api_url="http://fake", token="fake")
        with pytest.raises((AssertionError, ValueError)):
            runner.validate_namespace("")


class TestValidationChecks:
    def test_validate_incident_has_classification(self):
        from app.testing.scenario_runner import validate_incident
        incident = {
            "failure_class": "pods_crashlooping",
            "severity": "high",
            "signal_count": 3,
            "rca_output": '{"root_cause": "test"}',
            "remediation_options": [{"action": "delete pod"}],
            "evidence": {"signals": [{"signal_id": "1"}]},
        }
        checks = validate_incident(incident, expected_class="pods_crashlooping", expected_severity="high")
        names = [c["check"] for c in checks]
        assert "classification_correct" in names
        assert all(c["passed"] for c in checks if c["check"] == "classification_correct")

    def test_validate_incident_missing_rca(self):
        from app.testing.scenario_runner import validate_incident
        incident = {
            "failure_class": "pods_crashlooping",
            "severity": "high",
            "signal_count": 1,
            "rca_output": None,
            "remediation_options": [],
            "evidence": {"signals": []},
        }
        checks = validate_incident(incident, expected_class="pods_crashlooping", expected_severity="high")
        rca_check = [c for c in checks if c["check"] == "rca_produced"]
        assert len(rca_check) == 1
        assert not rca_check[0]["passed"]

    def test_validate_incident_wrong_classification(self):
        from app.testing.scenario_runner import validate_incident
        incident = {
            "failure_class": "config_error",
            "severity": "high",
            "signal_count": 1,
            "rca_output": '{"root_cause": "test"}',
            "remediation_options": [],
            "evidence": {"signals": [{"signal_id": "1"}]},
        }
        checks = validate_incident(incident, expected_class="pods_crashlooping", expected_severity="high")
        cls_check = [c for c in checks if c["check"] == "classification_correct"]
        assert not cls_check[0]["passed"]


class TestSignalInjection:
    def test_build_synthetic_signal(self):
        from app.testing.scenario_runner import build_synthetic_signal
        sig = build_synthetic_signal(
            namespace="deepfield",
            signal_type="pod_crashloop",
            severity="high",
            resource_name="chaos-pod-123",
        )
        assert sig["namespace"] == "deepfield"
        assert sig["signal_type"] == "pod_crashloop"
        assert sig["severity"] == "high"
        assert "cluster_id" in sig
