"""Live processing session with adjustable parameters."""

import time
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.generators.synthetic import SyntheticFleetGenerator
from app.normalizers.signal_normalizer import normalize_batch
from app.nanoagents.pipeline import run_pipeline
from app.correlation.engine import correlate
from app.routing.signal_router import route_signals, create_reasoning_tasks
from app.inference.client import MockInferenceClient, InferenceClient
from app.inference.router import resolve_model
from app.metrics.funnel import compute_funnel
from app.metrics.capacity import compute_capacity_projection


@dataclass
class SessionParams:
    clusters: int = 5
    failure_rate: float = 0.02
    concurrency: int = 10
    signals_per_cycle: int = 1000
    models_enabled: dict = field(default_factory=lambda: {
        "deepseek_r1_distill_qwen_14b_gaudi": True,
        "phi4_gaudi": True,
        "qwen3_14b_gaudi_a": True,
        "qwen3_14b_gaudi_b": True,
        "llama_3_1_70b_q4_xeon": False,
    })


@dataclass
class CycleMetrics:
    cycle: int = 0
    timestamp: str = ""
    raw_signals: int = 0
    normalized: int = 0
    dropped: int = 0
    suppressed: int = 0
    deduped: int = 0
    escalated: int = 0
    findings: int = 0
    reasoning_tasks: int = 0
    compression_ratio: float = 0
    llm_escalation_pct: float = 0
    inference_calls: int = 0
    avg_latency_ms: float = 0
    avg_tps: float = 0
    projected_clusters: int = 0
    cycle_duration_ms: float = 0
    cluster_state: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)


_sessions = {}


class LiveSession:
    def __init__(self, session_id: str, client: Optional[InferenceClient] = None, seed: int = 42):
        self.session_id = session_id
        self.client = client or MockInferenceClient(seed=seed)
        self.seed = seed
        self.params = SessionParams()
        self.status = "idle"
        self.cycle = 0
        self.history = []
        self.latest = None
        self.cumulative = {
            "total_raw_signals": 0,
            "total_reasoning_tasks": 0,
            "total_inference_calls": 0,
            "total_cycles": 0,
        }
        self._stop = threading.Event()
        self._thread = None
        self._max_benchmark_rps = 0
        self._benchmark_p95 = 0
        self.live = {}
        self._prom = None
        try:
            from app.inference.prometheus import PrometheusPoller
            self._prom = PrometheusPoller()
        except Exception:
            pass

    def update_params(self, **kwargs):
        for k, v in kwargs.items():
            if k == "models_enabled" and isinstance(v, dict):
                self.params.models_enabled.update(v)
            elif hasattr(self.params, k):
                setattr(self.params, k, v)

    def set_benchmark_baseline(self, rps: float, p95_ms: float):
        self._max_benchmark_rps = rps
        self._benchmark_p95 = p95_ms

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.status = "running"
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.status = "stopped"

    def _run_loop(self):
        while not self._stop.is_set():
            try:
                metrics = self._run_cycle()
                self.latest = metrics
                self.history.append(metrics)
                if len(self.history) > 100:
                    self.history = self.history[-100:]
            except Exception as e:
                self.latest = CycleMetrics(cycle=self.cycle, timestamp=datetime.now(timezone.utc).isoformat(),
                                           params={"error": str(e)})
            # Brief pause between cycles — but don't stop the loop on errors
            self._stop.wait(1.0)
        self.status = "stopped"

    def _run_cycle(self):
        self.cycle += 1
        t0 = time.monotonic()
        p = self.params

        gen = SyntheticFleetGenerator(
            "max_q", seed=self.seed + self.cycle,
            clusters=p.clusters,
            namespaces_per_cluster=max(5, p.clusters * 4),
            pods_per_namespace=10,
            total_events=p.signals_per_cycle,
            failure_rate=p.failure_rate,
        )
        clusters, raw_signals = gen.generate()
        normalized = normalize_batch(raw_signals)
        pipeline_result = run_pipeline(normalized)
        routing_result = route_signals(normalized, pipeline_result["decisions"])
        findings = correlate(routing_result["kept"])
        tasks = create_reasoning_tasks(findings)

        # Capture cluster state before inference
        cluster_before = {}
        if self._prom:
            try:
                cluster_before = self._prom.get_cluster_metrics().get("models", {})
            except Exception:
                pass

        enabled_models = [m for m, on in p.models_enabled.items() if on]
        inference_calls = 0
        total_latency = 0
        total_tps = 0
        total_tasks_to_run = min(len(tasks), 20)

        # Initialize live state for this cycle
        raw_count = len(raw_signals)
        task_count = len(tasks)
        compression_live = raw_count / task_count if task_count > 0 else float("inf")
        escalation_live = (task_count / raw_count * 100) if raw_count > 0 else 0

        total_filtered = pipeline_result["suppressed_count"] + pipeline_result["deduped_count"] + routing_result["dropped_count"]

        self.live = {
            "cycle": self.cycle,
            "phase": "filtering",
            "raw_signals": raw_count,
            "normalized": len(normalized),
            "dropped": total_filtered,
            "retained": routing_result["kept_count"],
            "findings": len(findings),
            "reasoning_tasks": task_count,
            "compression_ratio": round(compression_live, 1),
            "llm_escalation_pct": round(escalation_live, 4),
            "inference_total": total_tasks_to_run,
            "inference_completed": 0,
            "inference_calls": 0,
            "avg_latency_ms": 0,
            "avg_tps": 0,
            "last_model": "",
            "last_latency_ms": 0,
        }

        # Concurrent inference with live progress updates
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self.live["phase"] = "inference"
        self.live["model_activity"] = {m: {"in_flight": 0, "completed": 0, "total_latency": 0, "total_tps": 0} for m in enabled_models}

        tasks_to_run = tasks[:20]
        task_models = []
        for task in tasks_to_run:
            model = resolve_model(task)
            if model not in enabled_models and enabled_models:
                model = enabled_models[0]
            task_models.append((task, model))

        concurrency = min(p.concurrency, len(task_models)) if p.concurrency > 0 else min(10, len(task_models))
        lock = threading.Lock()

        def _infer(task_model):
            nonlocal inference_calls, total_latency, total_tps
            task, model = task_model
            if model in self.live.get("model_activity", {}):
                with lock:
                    self.live["model_activity"][model]["in_flight"] += 1

            resp = self.client.infer(model=model, prompt=task.prompt, max_tokens=64)

            with lock:
                if model in self.live.get("model_activity", {}):
                    self.live["model_activity"][model]["in_flight"] -= 1
                if resp.status == "success":
                    inference_calls += 1
                    total_latency += resp.latency_ms
                    total_tps += resp.tokens_per_second
                    self.live["inference_calls"] = inference_calls
                    self.live["inference_completed"] = inference_calls
                    self.live["avg_latency_ms"] = round(total_latency / inference_calls, 1)
                    self.live["avg_tps"] = round(total_tps / inference_calls, 1)
                    self.live["last_model"] = model
                    self.live["last_latency_ms"] = round(resp.latency_ms, 1)
                    if model in self.live.get("model_activity", {}):
                        self.live["model_activity"][model]["completed"] += 1
                        self.live["model_activity"][model]["total_latency"] += resp.latency_ms
                        self.live["model_activity"][model]["total_tps"] += resp.tokens_per_second
            return resp

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(_infer, tm) for tm in task_models]
            for f in as_completed(futures):
                f.result()  # propagate exceptions

        # Capture cluster state after inference
        cluster_after = {}
        if self._prom:
            try:
                cluster_after = self._prom.get_cluster_metrics().get("models", {})
            except Exception:
                pass

        cluster_snapshot = {}
        all_model_keys = set(list(cluster_before.keys()) + list(cluster_after.keys()))
        total_running = 0
        total_queued = 0
        total_kv = 0
        total_tps_cluster = 0
        total_rps_cluster = 0
        kv_count = 0
        for mk in all_model_keys:
            after = cluster_after.get(mk, {})
            running = after.get("requests_running", 0)
            queued = after.get("requests_waiting", 0)
            kv = after.get("kv_cache_pct", 0)
            tps_m = after.get("tokens_per_sec_1m", 0)
            rps_m = after.get("rps_1m", 0)
            cluster_snapshot[mk] = {
                "requests_running": running,
                "requests_waiting": queued,
                "kv_cache_pct": kv,
                "tokens_per_sec_1m": tps_m,
                "rps_1m": rps_m,
            }
            total_running += running
            total_queued += queued
            total_tps_cluster += tps_m
            total_rps_cluster += rps_m
            if kv > 0:
                total_kv += kv
                kv_count += 1

        cluster_state = {
            "models": cluster_snapshot,
            "total_requests_running": total_running,
            "total_requests_queued": total_queued,
            "total_tokens_per_sec": round(total_tps_cluster, 1),
            "total_rps": round(total_rps_cluster, 2),
            "avg_kv_cache_pct": round(total_kv / kv_count, 1) if kv_count > 0 else 0,
        }

        cycle_ms = (time.monotonic() - t0) * 1000
        raw_count = len(raw_signals)
        task_count = len(tasks)
        compression = raw_count / task_count if task_count > 0 else float("inf")
        escalation = (task_count / raw_count * 100) if raw_count > 0 else 0
        avg_lat = total_latency / inference_calls if inference_calls > 0 else 0
        avg_tps_val = total_tps / inference_calls if inference_calls > 0 else 0

        # Measured: deepseek 12.4 + phi4 11.8 + qwen3a 10.5 + qwen3b 9.3 = 44 RPS
        benchmark_rps = self._max_benchmark_rps if self._max_benchmark_rps > 0 else 44.0
        max_reasoning_per_min = benchmark_rps * 60
        signals_per_cluster = raw_count / max(p.clusters, 1)
        projected = int((max_reasoning_per_min * compression) / signals_per_cluster) if signals_per_cluster > 0 else 0

        self.cumulative["total_raw_signals"] += raw_count
        self.cumulative["total_reasoning_tasks"] += task_count
        self.cumulative["total_inference_calls"] += inference_calls
        self.cumulative["total_cycles"] += 1

        return CycleMetrics(
            cycle=self.cycle,
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw_signals=raw_count,
            normalized=len(normalized),
            dropped=total_filtered,
            suppressed=pipeline_result["suppressed_count"],
            deduped=pipeline_result["deduped_count"],
            escalated=len(pipeline_result["escalated"]),
            findings=len(findings),
            reasoning_tasks=task_count,
            compression_ratio=round(compression, 1),
            llm_escalation_pct=round(escalation, 4),
            inference_calls=inference_calls,
            avg_latency_ms=round(avg_lat, 1),
            avg_tps=round(avg_tps_val, 1),
            projected_clusters=projected,
            cycle_duration_ms=round(cycle_ms, 1),
            cluster_state=cluster_state,
            params=asdict(p),
        )

    def get_state(self):
        cum = self.cumulative.copy()
        total_raw = cum["total_raw_signals"]
        total_tasks = cum["total_reasoning_tasks"]
        cum["cumulative_compression_ratio"] = round(total_raw / total_tasks, 1) if total_tasks > 0 else 0
        cum["cumulative_escalation_pct"] = round((total_tasks / total_raw) * 100, 4) if total_raw > 0 else 0
        return {
            "session_id": self.session_id,
            "status": self.status,
            "cycle": self.cycle,
            "params": asdict(self.params),
            "latest": asdict(self.latest) if self.latest else None,
            "live": self.live if self.live else None,
            "cumulative": cum,
            "history": [{
                **{k: v for k, v in asdict(h).items() if k not in ("params",)},
                "cluster_state": {
                    "total_requests_running": asdict(h).get("cluster_state", {}).get("total_requests_running", 0),
                    "total_tokens_per_sec": asdict(h).get("cluster_state", {}).get("total_tokens_per_sec", 0),
                    "avg_kv_cache_pct": asdict(h).get("cluster_state", {}).get("avg_kv_cache_pct", 0),
                },
            } for h in self.history[-20:]],
        }


def get_session(session_id: str):
    return _sessions.get(session_id)


def create_session(client=None, seed=42):
    sid = str(uuid4())
    s = LiveSession(sid, client=client, seed=seed)
    _sessions[sid] = s
    return s
