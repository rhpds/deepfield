"""Synthetic session — lightweight signal generation for Demo and Simulator pages."""

import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from app.domain.models import RawSignal
from app.generators.synthetic import SyntheticFleetGenerator
from app.normalizers.signal_normalizer import normalize_signal
from app.nanoagents.pipeline import run_pipeline
from app.correlation.engine import correlate
from app.routing.signal_router import route_signals, create_reasoning_tasks
from app.inference.client import InferenceClient, MockInferenceClient
from app.inference.router import resolve_model


@dataclass
class SessionParams:
    clusters: int = 5
    failure_rate: float = 0.02
    signals_per_second: int = 100
    concurrency: int = 10
    models_enabled: dict = field(default_factory=lambda: {
        "deepseek_r1_distill_qwen_14b_gaudi": True,
        "phi4_gaudi": True,
        "qwen3_14b_gaudi_a": True,
        "qwen3_14b_gaudi_b": True,
        "llama_3_1_70b_q4_xeon": False,
    })


_sessions = {}


class SyntheticSession:
    """Lightweight session for synthetic signal generation (Demo / Simulator).

    No SignalStore, no agent_log, no K8s collectors — just the core pipeline:
    generate → normalize → nano-filter → correlate → route → infer → metrics.
    """

    def __init__(self, session_id: str, client: Optional[InferenceClient] = None, seed: int = 42):
        self.session_id = session_id
        self.client = client or MockInferenceClient(seed=seed)
        self.seed = seed
        self.params = SessionParams()
        self.status = "idle"

        self._signal_queue: deque = deque(maxlen=50000)

        self.metrics = {
            "raw_signals": 0,
            "normalized": 0,
            "dropped": 0,
            "retained": 0,
            "findings": 0,
            "reasoning_tasks": 0,
            "inference_completed": 0,
            "inference_in_flight": 0,
            "compression_ratio": 0,
            "llm_escalation_pct": 0,
            "avg_latency_ms": 0,
            "avg_tps": 0,
            "projected_clusters": 0,
            "signals_per_second": 0,
        }

        self.totals = {
            "raw_signals": 0,
            "reasoning_tasks": 0,
            "inference_calls": 0,
            "findings": 0,
            "dropped": 0,
        }

        self._ema_alpha = 0.2
        self._ema = {
            "compression_ratio": 0.0,
            "projected_clusters": 0.0,
            "signals_per_second": 0.0,
            "reasoning_tasks": 0.0,
            "llm_escalation_pct": 0.0,
        }

        self.model_stats: dict = {}
        self.snapshots: list = []
        self.live_inference: dict = {}

        self._stop = threading.Event()
        self._emitter_thread = None
        self._processor_thread = None
        self._inference_pool = None
        self._lock = threading.Lock()

        self._window_start = 0
        self._window_signals = 0
        self._window_tasks = 0
        self._window_dropped = 0
        self._window_findings = 0
        self._window_latency_sum = 0
        self._window_tps_sum = 0
        self._window_inference = 0
        self._last_snapshot = 0

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

    def start(self):
        if self._emitter_thread and self._emitter_thread.is_alive():
            return
        self._stop.clear()
        self.status = "running"
        self._window_start = time.monotonic()
        self._last_snapshot = time.monotonic()
        self._inference_pool = ThreadPoolExecutor(max_workers=20)
        self._emitter_thread = threading.Thread(target=self._emit_synthetic, daemon=True)
        self._processor_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._emitter_thread.start()
        self._processor_thread.start()

    def stop(self):
        self._stop.set()
        self.status = "stopped"
        if self._inference_pool:
            self._inference_pool.shutdown(wait=False)

    def _emit_synthetic(self):
        gen_seed = self.seed
        while not self._stop.is_set():
            p = self.params
            rate = max(1, p.signals_per_second)
            batch_size = max(1, rate // 10)

            gen = SyntheticFleetGenerator(
                "max_q", seed=gen_seed,
                clusters=p.clusters,
                namespaces_per_cluster=max(5, p.clusters * 4),
                pods_per_namespace=10,
                total_events=batch_size,
                failure_rate=p.failure_rate,
            )
            _, signals = gen.generate()
            for sig in signals:
                self._signal_queue.append(sig)

            gen_seed += 1
            self._stop.wait(0.1)

    def _process_loop(self):
        buffer = []

        while not self._stop.is_set():
            drained = 0
            while self._signal_queue and drained < 500:
                try:
                    sig = self._signal_queue.popleft()
                    buffer.append(sig)
                    drained += 1
                except IndexError:
                    break

            if not buffer:
                self._stop.wait(0.05)
                continue

            normalized = [normalize_signal(s) for s in buffer]

            pipeline_result = run_pipeline(normalized)
            routing_result = route_signals(normalized, pipeline_result["decisions"])
            kept = routing_result["kept"]
            total_dropped = pipeline_result["suppressed_count"] + pipeline_result["deduped_count"] + routing_result["dropped_count"]

            findings = correlate(kept) if len(kept) >= 2 else []
            tasks = create_reasoning_tasks(findings)

            max_in_flight = 30
            for task in tasks[:10]:
                with self._lock:
                    current_in_flight = self.metrics.get("inference_in_flight", 0)
                if current_in_flight >= max_in_flight:
                    break
                model = resolve_model(task)
                if self._inference_pool:
                    with self._lock:
                        self.metrics["inference_in_flight"] += 1
                    self._inference_pool.submit(self._do_inference, task, model)

            with self._lock:
                self._window_signals += len(buffer)
                self._window_tasks += len(tasks)
                self._window_dropped += total_dropped
                self._window_findings += len(findings)

                self.totals["raw_signals"] += len(buffer)
                self.totals["reasoning_tasks"] += len(tasks)
                self.totals["findings"] += len(findings)
                self.totals["dropped"] += total_dropped

                elapsed = max(0.1, time.monotonic() - self._window_start)
                self.metrics["raw_signals"] = self._window_signals
                self.metrics["dropped"] = self._window_dropped
                self.metrics["retained"] = self._window_signals - self._window_dropped
                self.metrics["findings"] = self._window_findings

                raw_sps = self._window_signals / elapsed
                raw_cr = (self._window_signals / self._window_tasks) if self._window_tasks > 0 else self._ema["compression_ratio"]
                raw_tasks = self._window_tasks
                raw_esc = (self._window_tasks / self._window_signals * 100) if self._window_signals > 0 else 0

                a = self._ema_alpha
                for key, raw in [("signals_per_second", raw_sps), ("compression_ratio", raw_cr),
                                  ("reasoning_tasks", raw_tasks), ("llm_escalation_pct", raw_esc)]:
                    if self._ema[key] == 0:
                        self._ema[key] = raw
                    else:
                        self._ema[key] = self._ema[key] * (1 - a) + raw * a

                self.metrics["signals_per_second"] = round(self._ema["signals_per_second"], 1)
                self.metrics["compression_ratio"] = round(self._ema["compression_ratio"], 1)
                self.metrics["reasoning_tasks"] = round(self._ema["reasoning_tasks"], 1)
                self.metrics["llm_escalation_pct"] = round(self._ema["llm_escalation_pct"], 4)

                benchmark_rps = 44.0
                max_reasoning_per_min = benchmark_rps * 60
                signals_per_cluster = self._ema["signals_per_second"] / max(self.params.clusters, 1)
                cr = self._ema["compression_ratio"]
                raw_projected = (max_reasoning_per_min * cr) / signals_per_cluster if signals_per_cluster > 0 and cr > 0 else 0
                if self._ema["projected_clusters"] == 0:
                    self._ema["projected_clusters"] = raw_projected
                else:
                    self._ema["projected_clusters"] = self._ema["projected_clusters"] * (1 - a) + raw_projected * a
                self.metrics["projected_clusters"] = int(self._ema["projected_clusters"])

            buffer.clear()

            now = time.monotonic()
            if now - self._last_snapshot >= 2.0:
                self._take_snapshot()
                self._last_snapshot = now
                self._window_start = now
                self._window_signals = 0
                self._window_tasks = 0
                self._window_dropped = 0
                self._window_findings = 0
                self._window_latency_sum = 0
                self._window_tps_sum = 0
                self._window_inference = 0

            self._stop.wait(0.05)

    def _do_inference(self, task, model):
        task_type = getattr(task, 'task_type', '')
        if task_type in ('root_cause_analysis', 'cross_cluster_correlation', 'fleet_summary', 'incident_analysis'):
            max_tokens = 1500
        else:
            max_tokens = 512
        resp = self.client.infer(model=model, prompt=task.prompt, max_tokens=max_tokens)
        with self._lock:
            self.metrics["inference_in_flight"] = max(0, self.metrics["inference_in_flight"] - 1)
            if resp.status == "success":
                self.metrics["inference_completed"] += 1
                self._window_inference += 1
                self._window_latency_sum += resp.latency_ms
                self._window_tps_sum += resp.tokens_per_second
                self.totals["inference_calls"] += 1

                if self._window_inference > 0:
                    self.metrics["avg_latency_ms"] = round(self._window_latency_sum / self._window_inference, 1)
                    self.metrics["avg_tps"] = round(self._window_tps_sum / self._window_inference, 1)

                if model not in self.model_stats:
                    self.model_stats[model] = {"calls": 0, "latency_sum": 0, "tps_sum": 0, "in_flight": 0}
                self.model_stats[model]["calls"] += 1
                self.model_stats[model]["latency_sum"] += resp.latency_ms
                self.model_stats[model]["tps_sum"] += resp.tokens_per_second

                self.live_inference = {
                    "last_model": model,
                    "last_latency_ms": round(resp.latency_ms, 1),
                    "in_flight": self.metrics["inference_in_flight"],
                    "completed": self.metrics["inference_completed"],
                }
            else:
                self.totals["inference_calls"] += 1

    def _take_snapshot(self):
        cluster_state = {}
        if self._prom:
            try:
                cm = self._prom.get_cluster_metrics()
                cluster_state = {
                    "total_requests_running": sum(m.get("requests_running", 0) for m in cm.get("models", {}).values()),
                    "total_tokens_per_sec": round(sum(m.get("tokens_per_sec_1m", 0) for m in cm.get("models", {}).values()), 1),
                    "avg_kv_cache_pct": 0,
                }
            except Exception:
                pass

        with self._lock:
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "signals_per_second": self.metrics["signals_per_second"],
                "compression_ratio": self.metrics["compression_ratio"],
                "reasoning_tasks": self._window_tasks,
                "projected_clusters": self.metrics["projected_clusters"],
                "avg_latency_ms": self.metrics["avg_latency_ms"],
                "avg_tps": self.metrics["avg_tps"],
                "inference_in_flight": self.metrics["inference_in_flight"],
                "cluster_state": cluster_state,
            }
            self.snapshots.append(snapshot)
            if len(self.snapshots) > 30:
                self.snapshots = self.snapshots[-30:]

    def get_state(self):
        try:
            total_raw = self.totals["raw_signals"]
            total_tasks = self.totals["reasoning_tasks"]
            return {
                "session_id": self.session_id,
                "status": self.status,
                "mode": "streaming",
                "params": asdict(self.params),
                "metrics": dict(self.metrics),
                "totals": {
                    **self.totals,
                    "cumulative_compression_ratio": round(total_raw / total_tasks, 1) if total_tasks > 0 else 0,
                    "cumulative_escalation_pct": round((total_tasks / total_raw) * 100, 4) if total_raw > 0 else 0,
                },
                "model_stats": {
                    k: {
                        "calls": v["calls"],
                        "avg_latency": round(v["latency_sum"] / v["calls"], 1) if v["calls"] > 0 else 0,
                        "avg_tps": round(v["tps_sum"] / v["calls"], 1) if v["calls"] > 0 else 0,
                    }
                    for k, v in self.model_stats.items()
                },
                "live_inference": self.live_inference,
                "agent_log": [],
                "snapshots": self.snapshots[-20:],
                "queue_depth": len(self._signal_queue),
            }
        except Exception:
            return {"session_id": self.session_id, "status": self.status, "metrics": dict(self.metrics), "totals": self.totals, "agent_log": [], "snapshots": [], "model_stats": {}, "live_inference": {}, "queue_depth": 0}


def create_synthetic_session(client=None, seed=42):
    import uuid
    sid = str(uuid.uuid4())
    s = SyntheticSession(sid, client=client, seed=seed)
    _sessions[sid] = s
    return s


def get_synthetic_session(session_id: str):
    return _sessions.get(session_id)
