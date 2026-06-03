"""Groups related signals into candidate findings."""

from collections import defaultdict
from typing import List
from uuid import uuid4

from app.domain.models import CandidateFinding, NormalizedSignal
from app.correlation.keys import namespace_key, cross_cluster_type_key

CORRELATION_MIN_SIGNALS = 2
FINDING_SEVERITY_PRIORITY = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _highest_severity(signals: List[NormalizedSignal]) -> str:
    if not signals:
        return "info"
    return max(signals, key=lambda s: FINDING_SEVERITY_PRIORITY.get(s.severity, 0)).severity


def _cluster_name(s: NormalizedSignal) -> str:
    src = s.evidence.get("source", "") if s.evidence else ""
    return src.split(":", 1)[-1] if ":" in src else ""


def _signal_to_evidence(s: NormalizedSignal) -> dict:
    d = {
        "signal_type": s.signal_type,
        "resource_kind": s.resource_kind,
        "resource_name": s.resource_name,
        "namespace": s.namespace,
        "severity": s.severity,
        "cluster": _cluster_name(s),
        "evidence": s.evidence,
    }
    return d


def correlate_by_namespace(signals: List[NormalizedSignal]) -> List[CandidateFinding]:
    groups = defaultdict(list)
    for s in signals:
        if s.severity in ("info",):
            continue
        groups[namespace_key(s)].append(s)

    findings = []
    for key, group in groups.items():
        if len(group) < CORRELATION_MIN_SIGNALS:
            continue
        findings.append(CandidateFinding(
            finding_id=uuid4(),
            clusters=list({s.cluster_id for s in group}),
            namespaces=list({s.namespace for s in group}),
            signal_ids=[s.signal_id for s in group],
            finding_type="namespace_correlation",
            severity=_highest_severity(group),
            correlation_keys={"key": key, "strategy": "namespace"},
            summary=f"Correlated {len(group)} signals in namespace {group[0].namespace}",
            evidence={
                "signal_types": list({s.signal_type for s in group}),
                "signals": [_signal_to_evidence(s) for s in group],
            },
        ))
    return findings


def correlate_cross_cluster(signals: List[NormalizedSignal]) -> List[CandidateFinding]:
    groups = defaultdict(list)
    for s in signals:
        if s.severity in ("info", "low"):
            continue
        groups[cross_cluster_type_key(s)].append(s)

    findings = []
    for key, group in groups.items():
        cluster_ids = {s.cluster_id for s in group}
        if len(cluster_ids) < 2:
            continue
        findings.append(CandidateFinding(
            finding_id=uuid4(),
            clusters=list(cluster_ids),
            namespaces=list({s.namespace for s in group}),
            signal_ids=[s.signal_id for s in group],
            finding_type="cross_cluster_correlation",
            severity=_highest_severity(group),
            correlation_keys={"key": key, "strategy": "cross_cluster"},
            summary=f"Cross-cluster pattern: {group[0].signal_type} across {len(cluster_ids)} clusters",
            evidence={
                "signal_types": list({s.signal_type for s in group}),
                "cluster_count": len(cluster_ids),
                "signals": [_signal_to_evidence(s) for s in group],
            },
        ))
    return findings


def correlate(signals: List[NormalizedSignal]) -> List[CandidateFinding]:
    findings = []
    findings.extend(correlate_by_namespace(signals))
    findings.extend(correlate_cross_cluster(signals))
    return findings
