"""Signal routing — nano → micro → macro agent pipeline.

Nano agents: deterministic filters (no LLM) — already run in nanoagents/pipeline.py
Micro agents: Xeon 6 CPU (OpenVINO, 15-28 tok/s) — fast triage on low/medium findings
Macro agents: Gaudi 3 GPU (50-60 tok/s) — deep reasoning on high/critical findings

Routing decisions are backed by the intel-inference-router corpora when available.
"""

import logging
from typing import List, Optional
from uuid import uuid4

from app.domain.models import (
    CandidateFinding,
    FilterDecision,
    NormalizedSignal,
    ReasoningTask,
)

try:
    from intel_inference_router import (
        CORPORA_TO_ENDPOINT,
        StrategyRouter,
        WorkloadBootstrapper,
        load_corpora,
        resolve_benchmark_task,
    )
    from intel_inference_router.scaler import InferenceScaler, PressureObserver
    from intel_inference_router.fleet_manager import FleetManager
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False

log = logging.getLogger(__name__)

# Micro agent models (Xeon 6 CPU — OpenVINO)
_MICRO_ROTATION = ["granite_2b_cpu", "phi3_mini_cpu", "qwen25_3b_cpu"]
_micro_idx = 0

# Macro agent models (Gaudi 3 GPU)
_MACRO_ROTATION = ["deepseek", "phi4", "qwen3b"]
_macro_idx = 0

_routing_mode = "production"
_industry = "basic"
_workload_type: Optional[str] = None

_strategy_router: Optional[object] = None
_bootstrapper: Optional[object] = None
_scaler: Optional[object] = None
_fleet_manager: Optional[object] = None
_pressure_observer: Optional[object] = None
_excluded_models: set = set()


def set_routing_mode(mode: str):
    global _routing_mode
    _routing_mode = mode


def set_industry(industry: str):
    global _industry
    _industry = industry


def set_workload_type(workload_type: Optional[str]):
    global _workload_type
    _workload_type = workload_type


def get_strategy_router():
    global _strategy_router
    if _strategy_router is None and _HAS_ROUTER:
        _strategy_router = StrategyRouter()
    return _strategy_router


def get_bootstrapper():
    global _bootstrapper
    if _bootstrapper is None and _HAS_ROUTER:
        _bootstrapper = WorkloadBootstrapper()
    return _bootstrapper


def get_scaler():
    global _scaler, _pressure_observer
    if _scaler is None and _HAS_ROUTER:
        _pressure_observer = PressureObserver()
        _scaler = InferenceScaler()
    return _scaler


def get_fleet_manager():
    global _fleet_manager
    if _fleet_manager is None and _HAS_ROUTER:
        _fleet_manager = FleetManager()
    return _fleet_manager


def update_pressure():
    """Read node pressure and update scaler state. Call periodically."""
    global _excluded_models
    scaler = get_scaler()
    if scaler and _pressure_observer:
        snapshot = _pressure_observer.read()
        state = scaler.observe_pressure(snapshot)
        _excluded_models = set(state.evicted_models)
        if state.last_action:
            log.info("Scaler action: %s (grade: %s)", state.last_action, state.scorecard.overall_grade)


def observe_signal(signal: NormalizedSignal, decisions: List[FilterDecision]):
    """Feed a signal to the workload bootstrapper for auto-detection."""
    bootstrapper = get_bootstrapper()
    if bootstrapper and not _workload_type:
        sig_dict = {
            "signal_type": signal.signal_type,
            "resource_kind": signal.resource_kind,
            "severity": signal.severity,
        }
        dec_dicts = [
            {"evidence": d.evidence, "outcome": d.outcome}
            for d in decisions
        ]
        bootstrapper.observe(sig_dict, dec_dicts)


def _resolve_workload_and_strategy():
    """Get the current workload type and strategy."""
    if _workload_type:
        wt, conf = _workload_type, 1.0
    elif _bootstrapper and _HAS_ROUTER:
        wt, conf = _bootstrapper.current_workload()
    else:
        wt, conf = "generic", 0.0

    strategy = None
    sr = get_strategy_router()
    if sr:
        strategy = sr.resolve_strategy(wt)

    return wt, conf, strategy


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

    # Determine tier from severity
    if finding.finding_type == "cross_cluster_correlation":
        tier = "macro"
    elif finding.severity in ("critical", "high"):
        tier = "macro"
    else:
        tier = "micro"

    # Try corpora-backed routing
    if _HAS_ROUTER:
        _, _, strategy = _resolve_workload_and_strategy()
        task_type = _finding_to_task_type(finding)
        industry = _industry
        if _bootstrapper:
            industry = _bootstrapper.current_industry() or _industry

        benchmark_task = resolve_benchmark_task(task_type, industry)
        corpora = load_corpora()
        if corpora:
            entry = corpora.lookup(
                industry, benchmark_task, tier,
                strategy=strategy,
                excluded_models=_excluded_models or None,
            )
            if entry:
                endpoint = CORPORA_TO_ENDPOINT.get(entry.config.model)
                if endpoint:
                    return endpoint

    # Fallback: round-robin
    if tier == "macro":
        if finding.finding_type == "cross_cluster_correlation":
            return "deepseek"
        model = _MACRO_ROTATION[_macro_idx % len(_MACRO_ROTATION)]
        _macro_idx += 1
        return model

    model = _MICRO_ROTATION[_micro_idx % len(_MICRO_ROTATION)]
    _micro_idx += 1
    return model


def _finding_to_task_type(finding: CandidateFinding) -> str:
    if finding.finding_type == "cross_cluster_correlation":
        return "deep_root_cause_analysis"
    if finding.severity in ("critical",) and len(finding.signal_ids) >= 5:
        return "deep_root_cause_analysis"
    if finding.severity in ("critical", "high"):
        return "root_cause_analysis"
    return "summarize_finding"


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
        CLASSIFY_SIGNAL_SYSTEM,
        CORRELATE_FINDINGS_SYSTEM,
        CORRELATION_SYSTEM,
        EXPLAIN_SIGNAL_SYSTEM,
        FILTER_NOISE_SYSTEM,
        RCA_SYSTEM,
        SUGGEST_REMEDIATION_SYSTEM,
        TRIAGE_SYSTEM,
        get_system_prompt,
    )

    tasks = []
    # Track namespaces across findings for correlate_findings trigger
    namespace_findings: dict = {}

    wt, wt_conf, strategy = _resolve_workload_and_strategy()

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
                "industry": _industry,
                "workload_type": wt,
                "workload_confidence": wt_conf,
                **({"_strategy": strategy} if strategy else {}),
                **({"_excluded_models": _excluded_models} if _excluded_models else {}),
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
        if has_escalation:
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
