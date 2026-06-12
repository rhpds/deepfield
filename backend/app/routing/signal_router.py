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


def _build_evidence_block(f: CandidateFinding, evidence_bundle: dict = None) -> dict:
    signals = f.evidence.get("signals", [])[:10]
    cluster_names = list({
        s.get("cluster", "") or s.get("evidence", {}).get("source", "").split(":", 1)[-1]
        for s in signals
        if s.get("cluster") or ":" in s.get("evidence", {}).get("source", "")
    }) or [str(c)[:8] for c in f.clusters]
    block = {
        "finding_type": f.finding_type,
        "severity": f.severity,
        "namespaces": f.namespaces,
        "clusters": cluster_names,
        "signal_count": len(f.signal_ids),
        "signals": signals,
    }
    if evidence_bundle:
        b = evidence_bundle.get("bundle", {})
        for key in ("events", "pod_statuses", "container_logs", "resource_metrics",
                     "prior_incidents", "deployments"):
            if b.get(key):
                block[key] = b[key]
    return block


def create_reasoning_tasks(findings: List[CandidateFinding], evidence_bundles: dict = None) -> List[ReasoningTask]:
    import json
    from app.agents.prompts import (
        RCA_SYSTEM, TRIAGE_SYSTEM, CORRELATION_SYSTEM,
        CLASSIFY_SIGNAL_SYSTEM, CORRELATE_FINDINGS_SYSTEM,
        SUGGEST_REMEDIATION_SYSTEM, EXPLAIN_SIGNAL_SYSTEM,
        FILTER_NOISE_SYSTEM, get_system_prompt,
    )

    tasks = []
    # Track namespaces across findings for correlate_findings trigger
    namespace_findings: dict = {}

    for f in findings:
        if f.severity == "info":
            continue

        model = _select_model_for_finding(f)
        eb = (evidence_bundles or {}).get(str(f.finding_id))
        evidence_block = _build_evidence_block(f, evidence_bundle=eb)

        # --- Primary task (deep RCA for critical cross-cluster or high-signal findings) ---
        if f.finding_type == "cross_cluster_correlation":
            task_type = "deep_root_cause_analysis"
            system_prompt = get_system_prompt("deep_rca") or CORRELATION_SYSTEM
        elif f.severity in ("critical",) and len(f.signal_ids) >= 5:
            task_type = "deep_root_cause_analysis"
            system_prompt = get_system_prompt("deep_rca") or RCA_SYSTEM
        elif f.severity in ("critical", "high"):
            task_type = "root_cause_analysis"
            system_prompt = RCA_SYSTEM
        else:
            task_type = "summarize_finding"
            system_prompt = TRIAGE_SYSTEM

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
                "namespaces": f.namespaces,
                "clusters": [str(c)[:8] for c in f.clusters],
                "signals": f.evidence.get("signals", [])[:20],
                **({"bundle_id": eb["bundle_id"]} if eb else {}),
            },
        ))

        # --- classify_signal: no failure_class after nano enrichment ---
        signals = f.evidence.get("signals", [])
        has_unclassified = any(
            not s.get("failure_class") for s in signals
        )
        if has_unclassified:
            micro_model = _MICRO_ROTATION[_micro_idx % len(_MICRO_ROTATION)]
            tasks.append(ReasoningTask(
                task_id=uuid4(),
                finding_id=f.finding_id,
                task_type="classify_signal",
                model_preference=micro_model,
                prompt=f"{CLASSIFY_SIGNAL_SYSTEM}\n\nEvidence:\n{json.dumps(evidence_block, indent=2)}",
                context={
                    "finding_type": f.finding_type,
                    "severity": f.severity,
                    "signal_count": len(f.signal_ids),
                    "tier": "micro",
                },
            ))

        # --- suggest_remediation: medium-severity findings ---
        if f.severity == "medium":
            micro_model = _MICRO_ROTATION[_micro_idx % len(_MICRO_ROTATION)]
            tasks.append(ReasoningTask(
                task_id=uuid4(),
                finding_id=f.finding_id,
                task_type="suggest_remediation",
                model_preference=micro_model,
                prompt=f"{SUGGEST_REMEDIATION_SYSTEM}\n\nEvidence:\n{json.dumps(evidence_block, indent=2)}",
                context={
                    "finding_type": f.finding_type,
                    "severity": f.severity,
                    "signal_count": len(f.signal_ids),
                    "tier": "micro",
                },
            ))

        # --- explain_signal: all escalated signals (findings with escalate evidence) ---
        has_escalation = any(
            s.get("evidence", {}).get("escalated") or s.get("outcome") == "escalate"
            for s in signals
        )
        if has_escalation or f.severity in ("high", "critical"):
            micro_model = _MICRO_ROTATION[_micro_idx % len(_MICRO_ROTATION)]
            tasks.append(ReasoningTask(
                task_id=uuid4(),
                finding_id=f.finding_id,
                task_type="explain_signal",
                model_preference=micro_model,
                prompt=f"{EXPLAIN_SIGNAL_SYSTEM}\n\nEvidence:\n{json.dumps(evidence_block, indent=2)}",
                context={
                    "finding_type": f.finding_type,
                    "severity": f.severity,
                    "signal_count": len(f.signal_ids),
                    "tier": "micro",
                },
            ))

        # --- filter_noise: low-confidence kept signals ---
        low_confidence_signals = [
            s for s in signals
            if s.get("confidence", 1.0) < 0.5
        ]
        if low_confidence_signals and f.severity == "low":
            micro_model = _MICRO_ROTATION[_micro_idx % len(_MICRO_ROTATION)]
            tasks.append(ReasoningTask(
                task_id=uuid4(),
                finding_id=f.finding_id,
                task_type="filter_noise",
                model_preference=micro_model,
                prompt=f"{FILTER_NOISE_SYSTEM}\n\nEvidence:\n{json.dumps(evidence_block, indent=2)}",
                context={
                    "finding_type": f.finding_type,
                    "severity": f.severity,
                    "signal_count": len(f.signal_ids),
                    "tier": "micro",
                },
            ))

        # Track namespaces for correlate_findings
        for ns in f.namespaces:
            namespace_findings.setdefault(ns, []).append(f)

    # --- correlate_findings: 2+ findings share a namespace ---
    correlated_pairs = set()
    for ns, ns_findings in namespace_findings.items():
        if len(ns_findings) >= 2:
            pair_key = tuple(sorted(str(ff.finding_id) for ff in ns_findings[:2]))
            if pair_key in correlated_pairs:
                continue
            correlated_pairs.add(pair_key)

            combined_evidence = {
                "shared_namespace": ns,
                "findings": [_build_evidence_block(ff) for ff in ns_findings[:4]],
            }
            micro_model = _MICRO_ROTATION[_micro_idx % len(_MICRO_ROTATION)]
            tasks.append(ReasoningTask(
                task_id=uuid4(),
                finding_id=ns_findings[0].finding_id,
                task_type="correlate_findings",
                model_preference=micro_model,
                prompt=f"{CORRELATE_FINDINGS_SYSTEM}\n\nEvidence:\n{json.dumps(combined_evidence, indent=2)}",
                context={
                    "finding_type": "correlate_findings",
                    "severity": max((ff.severity for ff in ns_findings), key=lambda s: ["info", "low", "medium", "high", "critical"].index(s)),
                    "signal_count": sum(len(ff.signal_ids) for ff in ns_findings),
                    "tier": "micro",
                    "namespace": ns,
                    "finding_count": len(ns_findings),
                },
            ))

    return tasks
