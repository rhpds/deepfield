"""Scenarios API — async synthetic end-to-end pipeline testing."""

import os
import threading
import asyncio
from fastapi import APIRouter, Depends

from app.auth import require_write_access

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])

_results: dict = {}
_running: dict = {}


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


@router.post("/run", dependencies=[Depends(require_write_access)])
async def run_scenario(body: dict):
    """Start a scenario in the background — returns immediately. Poll /results for status."""
    scenario_id = body.get("scenario_id", "")
    from app.testing.scenario_runner import SCENARIOS
    if scenario_id not in SCENARIOS:
        return {"error": f"Unknown scenario: {scenario_id}"}
    if scenario_id in _running and _running[scenario_id]:
        return {"status": "already_running", "scenario_id": scenario_id}

    _running[scenario_id] = True
    _results[scenario_id] = {"scenario_id": scenario_id, "status": "running", "name": SCENARIOS[scenario_id].name}

    def _run_in_thread():
        from app.testing.scenario_runner import ScenarioRunner
        cluster_url = os.environ.get("CLUSTER_1_API_URL", "")
        cluster_token = os.environ.get("CLUSTER_1_TOKEN", "")
        runner = ScenarioRunner(cluster_api_url=cluster_url, token=cluster_token)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(runner.run_scenario(scenario_id))
            _results[scenario_id] = result
        except Exception as e:
            _results[scenario_id] = {"scenario_id": scenario_id, "status": "error", "error": str(e)}
        finally:
            loop.close()
            _running[scenario_id] = False

    t = threading.Thread(target=_run_in_thread, daemon=True)
    t.start()
    return {"status": "started", "scenario_id": scenario_id}


@router.get("/results")
async def get_results():
    return {"results": _results}


@router.get("/results/{scenario_id}")
async def get_result(scenario_id: str):
    return _results.get(scenario_id, {"status": "not_run"})


@router.post("/run-all", dependencies=[Depends(require_write_access)])
async def run_all():
    """Run all scenarios sequentially in background. Poll /results for status."""
    from app.testing.scenario_runner import SCENARIOS
    if any(_running.get(sid) for sid in SCENARIOS):
        return {"status": "already_running"}

    for sid in SCENARIOS:
        _running[sid] = True
        _results[sid] = {"scenario_id": sid, "status": "queued", "name": SCENARIOS[sid].name}

    def _run_all_thread():
        from app.testing.scenario_runner import ScenarioRunner
        cluster_url = os.environ.get("CLUSTER_1_API_URL", "")
        cluster_token = os.environ.get("CLUSTER_1_TOKEN", "")
        runner = ScenarioRunner(cluster_api_url=cluster_url, token=cluster_token)
        loop = asyncio.new_event_loop()
        for sid in SCENARIOS:
            _results[sid]["status"] = "running"
            try:
                result = loop.run_until_complete(runner.run_scenario(sid))
                _results[sid] = result
            except Exception as e:
                _results[sid] = {"scenario_id": sid, "status": "error", "error": str(e)}
            _running[sid] = False
        loop.close()

    t = threading.Thread(target=_run_all_thread, daemon=True)
    t.start()
    return {"status": "started", "scenarios": list(SCENARIOS.keys())}
