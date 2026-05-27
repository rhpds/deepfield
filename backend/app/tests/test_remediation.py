"""TDD tests for remediation execution API."""

import pytest
from app.api.remediation import ALLOWED_COMMANDS, ExecuteRequest


def test_allowed_commands_include_safe_operations():
    assert "get" in ALLOWED_COMMANDS
    assert "describe" in ALLOWED_COMMANDS
    assert "logs" in ALLOWED_COMMANDS


def test_allowed_commands_include_mutation_operations():
    assert "delete_pod" in ALLOWED_COMMANDS
    assert "rollout_restart" in ALLOWED_COMMANDS
    assert "scale" in ALLOWED_COMMANDS


def test_no_dangerous_commands_allowed():
    dangerous = ["exec", "apply", "create", "patch", "edit", "replace", "drain", "cordon", "taint"]
    for cmd in dangerous:
        assert cmd not in ALLOWED_COMMANDS, f"Dangerous command '{cmd}' should not be allowed"


def test_execute_request_validates_fields():
    req = ExecuteRequest(
        cluster="infra01", namespace="test-ns",
        command="get", resource_kind="Pod", resource_name="my-pod",
    )
    assert req.cluster == "infra01"
    assert req.command == "get"


def test_execute_request_rejects_missing_fields():
    with pytest.raises(Exception):
        ExecuteRequest(cluster="infra01")


def test_execute_request_accepts_args():
    req = ExecuteRequest(
        cluster="infra01", namespace="test-ns",
        command="logs", resource_kind="Pod", resource_name="my-pod",
        args={"container": "app", "tailLines": 50},
    )
    assert req.args["container"] == "app"
