"""Full-detail signal, decision, finding, and inference store for observatory."""

from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import datetime, timezone


@dataclass
class AgentStats:
    total_evaluated: int = 0
    escalated: int = 0
    kept: int = 0
    suppressed: int = 0
    deduped: int = 0
    dropped: int = 0
    errors: int = 0


@dataclass
class ModelStats:
    total_calls: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_latency_ms: float = 0
    errors: int = 0
    task_types: Dict[str, int] = field(default_factory=dict)

    @property
    def avg_latency(self) -> float:
        return round(self.total_latency_ms / self.total_calls, 1) if self.total_calls > 0 else 0

    @property
    def avg_tps(self) -> float:
        total_time = self.total_latency_ms / 1000
        return round(self.total_tokens_out / total_time, 1) if total_time > 0 else 0


@dataclass
class ClusterStats:
    cluster_name: str = ""
    total_pods: int = 0
    pods_running: int = 0
    pods_pending: int = 0
    pods_failed: int = 0
    pods_crashloop: int = 0
    total_nodes: int = 0
    nodes_ready: int = 0
    nodes_pressure: int = 0
    total_events_warning: int = 0
    namespaces: Dict[str, int] = field(default_factory=dict)
    last_scan: str = ""


class SignalStore:
    def __init__(self, max_signals=200, max_decisions=200, max_findings=100, max_inferences=100):
        self.recent_signals: deque = deque(maxlen=max_signals)
        self.recent_decisions: deque = deque(maxlen=max_decisions)
        self.recent_findings: deque = deque(maxlen=max_findings)
        self.recent_inferences: deque = deque(maxlen=max_inferences)

        self.agent_stats: Dict[str, AgentStats] = {}
        self.model_stats: Dict[str, ModelStats] = {}
        self.cluster_stats: Dict[str, ClusterStats] = {}

    def add_signal(self, signal_dict: dict):
        """Store an actionable signal (already filtered to medium+)."""
        signal_dict["_ts"] = datetime.now(timezone.utc).isoformat()
        self.recent_signals.append(signal_dict)
        from app.db import enqueue_write
        enqueue_write("signals", {
            "cluster": signal_dict.get("cluster", ""),
            "namespace": signal_dict.get("namespace", ""),
            "resource_kind": signal_dict.get("resource_kind", ""),
            "resource_name": signal_dict.get("resource_name", ""),
            "signal_type": signal_dict.get("signal_type", ""),
            "severity": signal_dict.get("severity", ""),
            "raw_payload": signal_dict.get("raw_payload"),
            "evidence": signal_dict.get("evidence"),
        })

    def update_cluster_stats(self, cluster_name: str, signals: list):
        """Accumulate cluster infrastructure counts from signal batches."""
        if cluster_name not in self.cluster_stats:
            self.cluster_stats[cluster_name] = ClusterStats(cluster_name=cluster_name)
        cs = self.cluster_stats[cluster_name]
        for s in signals:
            sig_type = s.signal_type
            if sig_type == "pod_running":
                cs.pods_running += 1
            elif sig_type == "pod_pending":
                cs.pods_pending += 1
            elif sig_type == "pod_crashloop":
                cs.pods_crashloop += 1
            elif sig_type in ("pod_failed", "pod_imagepullbackoff"):
                cs.pods_failed += 1
            elif sig_type == "node_ready":
                cs.nodes_ready += 1
            elif sig_type == "node_pressure":
                cs.nodes_pressure += 1
            elif sig_type.startswith("event_") and sig_type not in ("event_normal", "event_pulling", "event_pulled", "event_created", "event_started", "event_scheduled", "event_successfulcreate", "event_successfuldelete"):
                cs.total_events_warning += 1
            ns = s.namespace
            if ns:
                cs.namespaces[ns] = cs.namespaces.get(ns, 0) + 1
        cs.total_pods = cs.pods_running + cs.pods_pending + cs.pods_crashloop + cs.pods_failed
        cs.total_nodes = cs.nodes_ready + cs.nodes_pressure
        cs.last_scan = datetime.now(timezone.utc).isoformat()

    def add_decision(self, decision_dict: dict):
        decision_dict["_ts"] = datetime.now(timezone.utc).isoformat()
        self.recent_decisions.append(decision_dict)
        from app.db import enqueue_write
        enqueue_write("decisions", {
            "filter_name": decision_dict.get("filter_name", ""),
            "outcome": decision_dict.get("outcome", ""),
            "reason": decision_dict.get("reason", ""),
            "signal_id": decision_dict.get("signal_id", ""),
            "evidence": decision_dict.get("evidence"),
        })

        agent = decision_dict.get("filter_name", "unknown")
        if agent not in self.agent_stats:
            self.agent_stats[agent] = AgentStats()
        stats = self.agent_stats[agent]
        stats.total_evaluated += 1
        outcome = decision_dict.get("outcome", "")
        if outcome == "escalate":
            stats.escalated += 1
        elif outcome == "keep":
            stats.kept += 1
        elif outcome == "suppress":
            stats.suppressed += 1
        elif outcome == "dedupe":
            stats.deduped += 1
        elif outcome == "drop":
            stats.dropped += 1

    def add_finding(self, finding_dict: dict):
        finding_dict["_ts"] = datetime.now(timezone.utc).isoformat()
        self.recent_findings.append(finding_dict)
        from app.db import enqueue_write
        enqueue_write("findings", {
            "finding_type": finding_dict.get("finding_type", ""),
            "severity": finding_dict.get("severity", ""),
            "summary": finding_dict.get("summary", ""),
            "namespaces": finding_dict.get("namespaces", []),
            "clusters": finding_dict.get("clusters", []),
            "signal_count": finding_dict.get("signal_count", 0),
            "evidence": finding_dict.get("evidence"),
        })

    def add_inference(self, inference_dict: dict):
        inference_dict["_ts"] = datetime.now(timezone.utc).isoformat()
        self.recent_inferences.append(inference_dict)
        from app.db import enqueue_write
        enqueue_write("inferences", {
            "model": inference_dict.get("model", ""),
            "hardware_lane": inference_dict.get("tier", ""),
            "task_type": inference_dict.get("task_type", ""),
            "severity": inference_dict.get("severity", ""),
            "prompt": inference_dict.get("prompt", ""),
            "output": inference_dict.get("output", ""),
            "tokens_in": inference_dict.get("tokens_in", 0),
            "tokens_out": inference_dict.get("tokens_out", 0),
            "latency_ms": inference_dict.get("latency_ms", 0),
            "error": inference_dict.get("error", ""),
        })

        model = inference_dict.get("model", "unknown")
        if model not in self.model_stats:
            self.model_stats[model] = ModelStats()
        ms = self.model_stats[model]
        ms.total_calls += 1
        ms.total_tokens_in += inference_dict.get("tokens_in", 0)
        ms.total_tokens_out += inference_dict.get("tokens_out", 0)
        ms.total_latency_ms += inference_dict.get("latency_ms", 0)
        if inference_dict.get("error"):
            ms.errors += 1
        task = inference_dict.get("task_type", "unknown")
        ms.task_types[task] = ms.task_types.get(task, 0) + 1

    def get_agent_summary(self) -> dict:
        return {
            name: {
                "total_evaluated": s.total_evaluated,
                "escalated": s.escalated,
                "kept": s.kept,
                "suppressed": s.suppressed,
                "deduped": s.deduped,
                "dropped": s.dropped,
                "errors": s.errors,
            }
            for name, s in self.agent_stats.items()
        }

    def get_model_summary(self) -> dict:
        return {
            name: {
                "total_calls": s.total_calls,
                "total_tokens_in": s.total_tokens_in,
                "total_tokens_out": s.total_tokens_out,
                "avg_latency": s.avg_latency,
                "avg_tps": s.avg_tps,
                "errors": s.errors,
                "task_types": dict(s.task_types),
            }
            for name, s in self.model_stats.items()
        }

    def get_cluster_summary(self) -> dict:
        return {
            name: asdict(s) for name, s in self.cluster_stats.items()
        }

    def get_recent_signals(self, limit: int = 50) -> list:
        return list(self.recent_signals)[-limit:]

    def get_recent_decisions(self, limit: int = 50) -> list:
        return list(self.recent_decisions)[-limit:]

    def get_recent_findings(self, limit: int = 30) -> list:
        return list(self.recent_findings)[-limit:]

    def get_recent_inferences(self, limit: int = 30) -> list:
        return list(self.recent_inferences)[-limit:]
