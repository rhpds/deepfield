"""Signal routing — nano → micro → macro agent pipeline.

Nano agents: deterministic filters (no LLM) — already run in nanoagents/pipeline.py
Micro agents: Xeon 6 CPU (OpenVINO, 15-28 tok/s) — fast triage on low/medium findings
Macro agents: Gaudi 3 GPU (50-60 tok/s) — deep reasoning on high/critical findings
"""

from typing import List
from uuid import uuid4

from app.domain.models import (
    CandidateFinding,
    FilterDecision,
    NormalizedSignal,
    ReasoningTask,
)

# Micro agent models (Xeon 6 CPU — OpenVINO)
_MICRO_ROTATION = ["granite_2b_cpu", "phi3_mini_cpu", "qwen25_3b_cpu"]
_micro_idx = 0

# Macro agent models (Gaudi 3 GPU)
_MACRO_ROTATION = ["deepseek", "qwen3", "phi4", "qwen3b"]
_macro_idx = 0

_routing_mode = "production"


def set_routing_mode(mode: str):
    global _routing_mode
    _routing_mode = mode


def _select_model_for_finding(finding: "CandidateFinding") -> str:
    global _micro_idx, _macro_idx

    if _routing_mode == "demo":
        all_models = _MICRO_ROTATION + _MACRO_ROTATION
        idx = _micro_idx + _macro_idx
        model = all_models[idx % len(all_models)]
        if model in _MICRO_ROTATION:
            _micro_idx += 1
        else:
            _macro_idx += 1
        return model

    # Production: route by severity
    if finding.finding_type == "cross_cluster_correlation":
        return "deepseek"

    if finding.severity in ("critical", "high"):
        model = _MACRO_ROTATION[_macro_idx % len(_MACRO_ROTATION)]
        _macro_idx += 1
        return model

    # Medium / low → micro agents on Xeon 6
    model = _MICRO_ROTATION[_micro_idx % len(_MICRO_ROTATION)]
    _micro_idx += 1
    return model


def route_signals(signals: List[NormalizedSignal], decisions: List[FilterDecision]) -> dict:
    escalated_ids = {d.signal_id for d in decisions if d.outcome == "escalate"}
    dropped_ids = {d.signal_id for d in decisions if d.outcome in ("drop", "suppress", "dedupe")}

    dropped = []
    kept = []
    for s in signals:
        if s.signal_id in dropped_ids:
            dropped.append(s)
        elif s.severity == "info" and s.signal_id not in escalated_ids:
            dropped.append(s)
        else:
            kept.append(s)

    return {
        "kept": kept,
        "dropped": dropped,
        "kept_count": len(kept),
        "dropped_count": len(dropped),
    }


def _build_evidence_block(f: CandidateFinding) -> dict:
    signals = f.evidence.get("signals", [])[:10]
    cluster_names = list({
        s.get("evidence", {}).get("source", "").split(":", 1)[-1]
        for s in signals
        if ":" in s.get("evidence", {}).get("source", "")
    }) or [str(c)[:8] for c in f.clusters]
    return {
        "finding_type": f.finding_type,
        "severity": f.severity,
        "namespaces": f.namespaces,
        "clusters": cluster_names,
        "signal_count": len(f.signal_ids),
        "signals": signals,
    }


def create_reasoning_tasks(findings: List[CandidateFinding]) -> List[ReasoningTask]:
    import json
    from app.agents.prompts import RCA_SYSTEM, TRIAGE_SYSTEM, CORRELATION_SYSTEM

    tasks = []
    for f in findings:
        if f.severity == "info":
            continue

        model = _select_model_for_finding(f)

        if f.finding_type == "cross_cluster_correlation":
            task_type = "cross_cluster_correlation"
            system_prompt = CORRELATION_SYSTEM
        elif f.severity in ("critical", "high"):
            task_type = "root_cause_analysis"
            system_prompt = RCA_SYSTEM
        else:
            task_type = "summarize_finding"
            system_prompt = TRIAGE_SYSTEM

        evidence_block = _build_evidence_block(f)
        prompt = f"{system_prompt}\n\nEvidence:\n{json.dumps(evidence_block, indent=2)}"

        tasks.append(ReasoningTask(
            task_id=uuid4(),
            finding_id=f.finding_id,
            task_type=task_type,
            model_preference=model,
            prompt=prompt,
            context={
                "finding_type": f.finding_type,
                "severity": f.severity,
                "signal_count": len(f.signal_ids),
                "tier": "macro" if f.severity in ("critical", "high") else "micro",
            },
        ))

    return tasks
