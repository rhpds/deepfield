"""Scenarios API — synthetic end-to-end pipeline testing."""

import os
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])

_last_results: dict = {}


@router.get("")
async def list_scenarios():
    from app.testing.scenario_runner import SCENARIOS
    return {
        "scenarios": [
            {"id": s.id, "name": s.name, "namespace": s.namespace,
             "inject_type": s.inject_type, "expected_classification": s.expected_classification,
             "execute_remediation": s.execute_remediation, "description": s.description}
            for s in SCENARIOS.values()
        ]
    }


@router.post("/run")
async def run_scenario(body: dict):
    scenario_id = body.get("scenario_id", "")
    from app.testing.scenario_runner import ScenarioRunner, SCENARIOS
    if scenario_id not in SCENARIOS:
        return {"error": f"Unknown scenario: {scenario_id}"}

    cluster_url = os.environ.get("CLUSTER_1_API_URL", "")
    cluster_token = os.environ.get("CLUSTER_1_TOKEN", "")
    runner = ScenarioRunner(cluster_api_url=cluster_url, token=cluster_token)
    result = await runner.run_scenario(scenario_id)
    _last_results[scenario_id] = result
    return result


@router.get("/results")
async def get_results():
    return {"results": _last_results}
