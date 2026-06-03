"""Streaming session — continuous signal processing without cycles."""

import logging
import time
import threading
import random
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deepfield.session")
from concurrent.futures import ThreadPoolExecutor


# ---------- thread-level crash safety ----------
def _thread_exception_hook(args):
    """Catch unhandled exceptions in *any* thread (Python 3.8+)."""
    logger.error(
        "Thread %s died with unhandled exception: %s",
        args.thread.name if args.thread else "<unknown>",
        args.exc_value,
        exc_info=(args.exc_type, args.exc_value, args.exc_tb),
    )

threading.excepthook = _thread_exception_hook
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from app.domain.models import RawSignal
from app.generators.synthetic import SyntheticFleetGenerator
from app.generators.signal_types import SIGNAL_RESOURCE_KIND
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


def get_active_sessions() -> dict:
    """Return the dict of active sessions for signal injection."""
    return _sessions


class StreamingSession:
    def __init__(self, session_id: str, client: Optional[InferenceClient] = None, seed: int = 42,
                 source: str = "synthetic", cluster_configs: Optional[list] = None, scan_interval: int = 30):
        self.session_id = session_id
        self.client = client or MockInferenceClient(seed=seed)
        self.seed = seed
        self.source = source
        self.scan_interval = scan_interval
        self.cluster_configs = cluster_configs or []
        self.params = SessionParams()
        self.status = "idle"
        self.target_namespaces: Optional[list] = None

        # Signal queue
        self._signal_queue: deque = deque(maxlen=50000)

        # Metrics — rolling window
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

        # Cumulative totals — seeded from DB on startup
        self.totals = self._load_totals_from_db()

        # EMA smoothing (alpha = 0.2 means 80% previous + 20% new)
        self._ema_alpha = 0.2
        self._ema = {
            "compression_ratio": 0.0,
            "projected_clusters": 0.0,
            "signals_per_second": 0.0,
            "reasoning_tasks": 0.0,
            "llm_escalation_pct": 0.0,
        }

        # Per-model stats
        self.model_stats: dict = {}

        # Agent observability
        self.agent_log: list = []
        from app.session.signal_store import SignalStore
        self.store = SignalStore()

        # Finding cooldown — prevent re-inferencing same finding on each rescan
        self._finding_cooldown: dict = {}
        self._finding_cooldown_secs = 60
        self._finding_cooldown_max = 500

        # Live collectors (set by _emit_live)
        self._collectors: list = []

        # Correlation buffer — accumulates kept signals across batches
        self._correlation_buffer: list = []

        # Time-series snapshots (every 2 seconds)
        self.snapshots: list = []

        # Live inference state
        self.live_inference: dict = {}

        # Inference queue — decouples processor from inference execution
        self._inference_queue: deque = deque(maxlen=100)

        # Threads
        self._stop = threading.Event()
        self._emitter_thread = None
        self._processor_thread = None
        self._inference_worker = None
        self._watchdog_thread = None
        self._inference_pool = None
        self._lock = threading.RLock()

        # Heartbeat — updated every process-loop iteration
        self._last_heartbeat = 0.0
        self._last_stats_flush = time.monotonic()
        self._heartbeat_lock = threading.Lock()
        self._process_loop_restarts = 0

        # Window tracking
        self._window_start = 0
        self._window_signals = 0
        self._window_tasks = 0
        self._window_dropped = 0
        self._window_findings = 0
        self._window_latency_sum = 0
        self._window_tps_sum = 0
        self._window_inference = 0
        self._last_snapshot = 0

        # Cluster profiles (adaptive thresholds) — one per cluster
        self._cluster_profile = None
        self._cluster_profiles: dict = {}
        if self.source == "live" and self.cluster_configs:
            from app.session.cluster_profile import get_profile, load_profiles_from_db
            load_profiles_from_db()
            for cfg in self.cluster_configs:
                cname = cfg.get("name", "unknown")
                self._cluster_profiles[cname] = get_profile(cname)
                logger.info("Loaded cluster profile for %s (confidence=%.2f)",
                            cname, self._cluster_profiles[cname].confidence)
            first_name = self.cluster_configs[0].get("name", "unknown")
            self._cluster_profile = self._cluster_profiles[first_name]

        # Prometheus
        self._prom = None
        try:
            from app.inference.prometheus import PrometheusPoller
            self._prom = PrometheusPoller()
        except Exception:
            pass

    @staticmethod
    def _load_totals_from_db() -> dict:
        """Seed cumulative totals from DB so dashboard isn't empty after restart."""
        defaults = {"raw_signals": 0, "reasoning_tasks": 0, "inference_calls": 0, "findings": 0, "dropped": 0, "retained": 0}
        import os, threading
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return defaults

        result_box = [defaults]

        def _sync_load():
            try:
                import asyncio, asyncpg
                async def _do():
                    conn = await asyncpg.connect(db_url)
                    try:
                        row = await conn.fetchrow(
                            "SELECT raw_signals, reasoning_tasks, inference_calls, findings, dropped "
                            "FROM session_snapshots ORDER BY captured_at DESC LIMIT 1"
                        )
                        if row:
                            return {
                                "raw_signals": row["raw_signals"] or 0,
                                "reasoning_tasks": row["reasoning_tasks"] or 0,
                                "inference_calls": row["inference_calls"] or 0,
                                "findings": row["findings"] or 0,
                                "dropped": row["dropped"] or 0,
                                "retained": 0,
                            }
                        return defaults
                    finally:
                        await conn.close()
                loop = asyncio.new_event_loop()
                result_box[0] = loop.run_until_complete(_do())
                loop.close()
            except Exception:
                pass

        t = threading.Thread(target=_sync_load)
        t.start()
        t.join(timeout=10)

        if result_box[0]["raw_signals"] > 0:
            logging.getLogger(__name__).info(
                "Seeded totals from DB: raw=%d, findings=%d, inferences=%d",
                result_box[0]["raw_signals"], result_box[0]["findings"], result_box[0]["inference_calls"],
            )
        return result_box[0]

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
        self._last_heartbeat = time.monotonic()
        self._inference_pool = ThreadPoolExecutor(max_workers=20)
        self._emitter_thread = threading.Thread(
            target=self._emit_signals, daemon=True, name="deepfield-emitter")
        self._processor_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="deepfield-processor")
        self._inference_worker = threading.Thread(
            target=self._inference_loop, daemon=True, name="deepfield-inference")
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="deepfield-watchdog")
        self._emitter_thread.start()
        self._processor_thread.start()
        self._inference_worker.start()
        self._watchdog_thread.start()

    def stop(self):
        self._stop.set()
        self.status = "stopped"
        if self._inference_pool:
            self._inference_pool.shutdown(wait=False)

    def _emit_signals(self):
        """Emits signals from synthetic generator or live cluster collector."""
        if self.source == "live":
            self._emit_live()
            return
        self._emit_synthetic()

    def _emit_live(self):
        """Watches real clusters via K8s watch API + periodic re-scans."""
        from app.collectors.openshift import OpenShiftCollector
        collectors = []
        for cfg in self.cluster_configs:
            c = OpenShiftCollector(
                cluster_name=cfg["name"],
                api_url=cfg["api_url"],
                token=cfg.get("token", ""),
                include_namespaces=cfg.get("include_namespaces"),
                exclude_namespaces=cfg.get("exclude_namespaces"),
            )
            c.start_watching()
            collectors.append(c)
        self._collectors = collectors

        last_rescan = time.monotonic()
        rescan_interval = self.scan_interval

        while not self._stop.is_set():
            for c in collectors:
                signals = c.drain_signals()
                for sig in signals:
                    self._signal_queue.append(sig)

            if time.monotonic() - last_rescan >= rescan_interval:
                for c in collectors:
                    c.rescan()
                self._sync_infra_counts()
                last_rescan = time.monotonic()

            self._stop.wait(0.5)

        for c in collectors:
            c.stop()

    def _sync_infra_counts(self):
        """Pull current infra counts from collectors and reset cluster stats."""
        if not self._collectors:
            return
        for c in self._collectors:
            counts = c.get_infra_counts()
            cs = self.store.cluster_stats.get(c.cluster_name)
            if cs:
                cs.pods_running = counts.get("pods_running", 0)
                cs.pods_pending = counts.get("pods_pending", 0)
                cs.pods_failed = counts.get("pods_failed", 0)
                cs.pods_crashloop = counts.get("pods_crashloop", 0)
                cs.nodes_ready = counts.get("nodes_ready", 0)
                cs.nodes_pressure = counts.get("nodes_pressure", 0)
                cs.total_pods = cs.pods_running + cs.pods_pending + cs.pods_crashloop + cs.pods_failed
                cs.total_nodes = cs.nodes_ready + cs.nodes_pressure
                cs.total_events_warning = 0

    def _emit_synthetic(self):
        """Continuously generates synthetic signals at the configured rate."""
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
            self._stop.wait(0.1)  # 10 batches per second

    # Maximum signals to drain per iteration — smaller chunks reduce memory
    # pressure and per-batch processing time on constrained environments.
    _BATCH_LIMIT = 50

    def _process_loop(self):
        """Continuously drains signal queue, normalizes, filters, correlates, routes.

        Updates ``self._last_heartbeat`` every iteration so the watchdog can
        detect a stalled / killed thread and restart it.
        """
        buffer = []
        logger.warning(
            "_process_loop STARTED — thread alive (restarts=%d)",
            self._process_loop_restarts,
        )

        _phase = "init"
        _iter_count = 0
        while not self._stop.is_set():
          try:
            _iter_count += 1
            _phase = "heartbeat"
            # Update heartbeat for watchdog
            with self._heartbeat_lock:
                self._last_heartbeat = time.monotonic()

            _phase = "drain"
            # Drain queue (capped to _BATCH_LIMIT per iteration)
            drained = 0
            while self._signal_queue and drained < self._BATCH_LIMIT:
                try:
                    sig = self._signal_queue.popleft()
                    buffer.append(sig)
                    drained += 1
                except IndexError:
                    break

            if drained > 0:
                logger.warning("DRAIN: %d signals, buffer=%d", drained, len(buffer))
            _phase = "snapshot"
            # Always tick snapshots even when idle
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

            # Persist stats to DB every 10 seconds
            if now - self._last_stats_flush >= 10.0:
                self._persist_stats()
                self._update_cluster_profile()
                self._last_stats_flush = now

            if not buffer:
                _phase = "idle"
                self._stop.wait(0.05)
                continue

            _phase = "normalize"
            # Filter by target namespaces if set (for scoped demo sessions)
            if self.target_namespaces:
                buffer = [s for s in buffer if any(
                    getattr(s, 'namespace', '') == ns or getattr(s, 'namespace', '').startswith(ns.rstrip('*'))
                    for ns in self.target_namespaces
                )]
                if not buffer:
                    continue

            # Normalize
            try:
                normalized = [normalize_signal(s) for s in buffer]
            except Exception as e:
                logger.warning("normalize error: %s", e)
                buffer.clear()
                continue

            # Update cluster stats from ALL signals (for infra overview cards)
            try:
                by_cluster: dict = {}
                for s in buffer:
                    cn = s.source.split(":", 1)[-1] if ":" in s.source else s.source
                    by_cluster.setdefault(cn, []).append(s)
                for cn, sigs in by_cluster.items():
                    self.store.update_cluster_stats(cn, sigs)
            except Exception as e:
                logger.warning("cluster stats error: %s", e)

            # Store only actionable signals (medium/high/critical) — skip info noise
            try:
                for raw, norm in zip(buffer, normalized):
                    if norm.severity in ("info", "low"):
                        continue
                    cluster_name = raw.source.split(":", 1)[-1] if ":" in raw.source else raw.source
                    if "e2e" in raw.namespace:
                        logger.warning("STORING E2E SIGNAL: ns=%s type=%s sev=%s", raw.namespace, raw.signal_type, norm.severity)
                    self.store.add_signal({
                        "signal_type": raw.signal_type, "namespace": raw.namespace,
                        "resource_kind": raw.resource_kind, "resource_name": raw.resource_name,
                        "source": raw.source, "cluster": cluster_name, "severity": norm.severity,
                        "raw_payload": raw.raw_payload, "timestamp": raw.timestamp.isoformat(),
                    })
            except Exception as e:
                logger.warning("store signal error: %s", e)

            _phase = "pipeline"
            # ------ Pipeline (isolated) ------
            kept = []
            total_dropped = len(buffer)
            findings = []
            new_findings = []

            try:
                pipeline_result = run_pipeline(normalized, cluster_profile=self._cluster_profile)
            except Exception as e:
                logger.error("run_pipeline crashed: %s", e, exc_info=True)
                pipeline_result = None

            if pipeline_result is not None:
                try:
                    routing_result = route_signals(normalized, pipeline_result["decisions"])
                    kept = routing_result["kept"]
                    total_dropped = (pipeline_result["suppressed_count"]
                                     + pipeline_result["deduped_count"]
                                     + routing_result["dropped_count"])

                    for d in pipeline_result.get("decisions", []):
                        self.store.add_decision({
                            "filter_name": d.filter_name, "outcome": d.outcome,
                            "reason": d.reason_code, "signal_id": str(d.signal_id)[:8],
                            "evidence": d.evidence,
                        })
                        if d.outcome == "escalate":
                            self._log_event("nano", "escalate", {
                                "filter": d.filter_name, "signal_id": str(d.signal_id)[:8],
                                "reason": d.reason_code, "evidence": d.evidence,
                            })
                            self._push_escalation(d)
                except Exception as e:
                    logger.error("route_signals crashed: %s", e, exc_info=True)

            # Phase 1 Kafka dual-write: publish kept/escalated signals
            try:
                from app.integrations.kafka_publisher import publish_filtered_signal
                for s in kept:
                    publish_filtered_signal({
                        "signal_type": s.signal_type, "namespace": s.namespace,
                        "resource_kind": s.resource_kind, "resource_name": s.resource_name,
                        "severity": s.severity, "source": getattr(s, "source", ""),
                    })
            except Exception:
                pass

            _phase = "correlate"
            # ------ Correlate (isolated) — only when new signals arrive ------
            if kept:
                for s in kept:
                    self._correlation_buffer.append(s)
                if len(self._correlation_buffer) > 500:
                    self._correlation_buffer = self._correlation_buffer[-500:]

                if len(self._correlation_buffer) >= 2:
                    try:
                        findings = correlate(self._correlation_buffer)
                    except Exception as e:
                        logger.error("correlate crashed: %s", e, exc_info=True)
                        findings = []

            try:
                now_ts = time.monotonic()
                if len(self._finding_cooldown) > self._finding_cooldown_max:
                    cutoff = now_ts - self._finding_cooldown_secs * 2
                    self._finding_cooldown = {k: v for k, v in self._finding_cooldown.items() if v > cutoff}
                for f in findings:
                    key = f"{f.finding_type}:{','.join(sorted(f.namespaces))}"
                    last_seen = self._finding_cooldown.get(key, 0)
                    if now_ts - last_seen >= self._finding_cooldown_secs:
                        new_findings.append(f)
                        self._finding_cooldown[key] = now_ts

                        cluster_names = list(self.store.cluster_stats.keys()) or ["infra01"]
                        finding_dict = {
                            "finding_type": f.finding_type, "severity": f.severity,
                            "summary": f.summary, "namespaces": f.namespaces,
                            "signal_count": len(f.signal_ids),
                            "clusters": cluster_names,
                        }
                        self.store.add_finding(finding_dict)
                        self._log_event("correlation", "finding", {
                            "type": f.finding_type, "severity": f.severity,
                            "summary": f.summary, "signals": len(f.signal_ids),
                            "namespaces": f.namespaces[:3],
                        })
                        try:
                            from app.integrations.kafka_publisher import publish_finding
                            publish_finding(finding_dict)
                        except Exception:
                            pass
            except Exception as e:
                logger.error("finding bookkeeping crashed: %s", e, exc_info=True)

            # Create reasoning tasks from new findings only
            tasks = create_reasoning_tasks(new_findings)

            # Enqueue inference tasks — dedicated worker thread processes them
            for task in tasks[:4]:
                model = resolve_model(task)
                self._inference_queue.append((task, model))

            # Update window metrics
            with self._lock:
                self._window_signals += len(buffer)
                self._window_tasks += len(tasks)
                self._window_dropped += total_dropped
                self._window_findings += len(new_findings)

                self.totals["raw_signals"] += len(buffer)
                self.totals["reasoning_tasks"] += len(tasks)
                self.totals["findings"] += len(new_findings)
                self.totals["dropped"] += total_dropped
                self.totals["retained"] = self.totals.get("retained", 0) + len(kept)

                # Compute raw window metrics
                elapsed = max(0.1, time.monotonic() - self._window_start)
                self.metrics["raw_signals"] = self._window_signals
                self.metrics["dropped"] = self._window_dropped
                self.metrics["retained"] = len(kept)
                self.metrics["findings"] = self._window_findings

                raw_sps = self._window_signals / elapsed
                raw_cr = (self._window_signals / self._window_tasks) if self._window_tasks > 0 else self._ema["compression_ratio"]
                raw_tasks = self._window_tasks
                raw_esc = (self._window_tasks / self._window_signals * 100) if self._window_signals > 0 else 0

                # EMA smoothing — blend new values with previous for stability
                a = self._ema_alpha
                for key, raw in [("signals_per_second", raw_sps), ("compression_ratio", raw_cr),
                                  ("reasoning_tasks", raw_tasks), ("llm_escalation_pct", raw_esc)]:
                    if self._ema[key] == 0:
                        self._ema[key] = raw  # first value, no smoothing
                    else:
                        self._ema[key] = self._ema[key] * (1 - a) + raw * a

                self.metrics["signals_per_second"] = round(self._ema["signals_per_second"], 1)
                self.metrics["compression_ratio"] = round(self._ema["compression_ratio"], 1)
                self.metrics["reasoning_tasks"] = round(self._ema["reasoning_tasks"], 1)
                self.metrics["llm_escalation_pct"] = round(self._ema["llm_escalation_pct"], 4)

                # Projected clusters — use smoothed compression ratio
                # Measured saturation points (from benchmark sweep):
                # deepseek: 12.4 RPS, phi4: 11.8 RPS, qwen3a: 10.5 RPS, qwen3b: 9.3 RPS
                # Total combined fleet: 44 RPS
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

            _phase = "done"
            buffer.clear()
            self._stop.wait(0.05)

          except BaseException as e:
            logger.error("Process loop error at phase=%s iter=%d: %s", _phase, _iter_count, e, exc_info=True)
            buffer.clear()
            self._stop.wait(1)

        logger.warning("_process_loop EXITED (stop=%s)", self._stop.is_set())

    def _inference_loop(self):
        """Dedicated thread that processes inference tasks one at a time."""
        while not self._stop.is_set():
            if self._inference_queue:
                try:
                    task, model = self._inference_queue.popleft()
                except IndexError:
                    self._stop.wait(1.0)
                    continue
                tier = "micro" if "cpu" in model or "granite" in model or "phi3" in model or "qwen25" in model else "macro"
                self._log_event(tier, "inference_start", {
                    "task_type": task.task_type,
                    "model": model,
                    "severity": task.context.get("severity", ""),
                    "prompt": task.prompt[:80],
                })
                with self._lock:
                    self.metrics["inference_in_flight"] += 1
                self._do_inference(task, model)
            else:
                self._stop.wait(1.0)

    def _update_cluster_profile(self):
        """Update cluster profiles with recent signal patterns — one per cluster."""
        if not self._cluster_profiles:
            return
        try:
            from app.session.cluster_profile import persist_profile
            duration_hours = max(0.01, (time.monotonic() - self._window_start) / 3600)

            # Bucket recent signals by cluster
            per_cluster: dict = {}
            for s in list(self.store.recent_signals)[-500:]:
                cluster = s.get("cluster", "")
                if not cluster:
                    src = s.get("source", "")
                    cluster = src.split(":", 1)[-1] if ":" in src else src
                if cluster:
                    per_cluster.setdefault(cluster, []).append(s)

            for cluster_name, profile in self._cluster_profiles.items():
                signals = per_cluster.get(cluster_name, [])
                signal_counts: dict = {}
                namespace_counts: dict = {}
                for s in signals:
                    signal_counts[s.get("signal_type", "")] = signal_counts.get(s.get("signal_type", ""), 0) + 1
                    ns = s.get("namespace", "")
                    if ns:
                        namespace_counts[ns] = namespace_counts.get(ns, 0) + 1

                if signal_counts:
                    profile.update_from_signals(
                        signal_counts, namespace_counts,
                        total_signals=self.totals["raw_signals"],
                        duration_hours=duration_hours,
                    )

                # Noise scores — approximate from overall suppression ratio
                if namespace_counts:
                    retained = self.totals.get("retained", 0)
                    total = self.totals.get("raw_signals", 0)
                    drop_ratio = 1.0 - (retained / total) if total > retained > 0 else 0.5
                    ns_total = dict(namespace_counts)
                    ns_suppressed = {ns: int(c * drop_ratio) for ns, c in namespace_counts.items()}
                    profile.update_noise_scores(ns_total, ns_suppressed)

                # Model health — shared across clusters (same inference fleet)
                for model, stats in self.model_stats.items():
                    calls = stats.get("calls", 0)
                    if calls > 0:
                        errors = stats.get("errors", 0)
                        profile.model_health[model] = {
                            "calls": calls, "errors": errors,
                            "total_latency": stats.get("latency_sum", 0),
                            "error_rate": round(errors / calls, 4),
                            "avg_latency": round(stats.get("latency_sum", 0) / calls, 1),
                        }

                persist_profile(profile)
        except Exception as e:
            logger.warning("Profile update failed: %s", e)

    def _feed_incident(self, task, model: str, output: str):
        """Feed macro-agent RCA results into the incident manager.

        Only root_cause_analysis (macro tier) creates incidents. The RCA output
        contains the full analysis — root cause, category, evidence chain,
        remediation steps — and includes ALL correlated signals from the finding.

        Micro-agent results (classify, explain, suggest) enrich existing incidents
        but never create new ones.
        """
        try:
            import json as _json
            from app.api.incidents import get_manager
            mgr = get_manager()

            ns = task.context.get("namespace") or ""
            if not ns and task.context.get("namespaces"):
                nsl = task.context["namespaces"]
                ns = nsl[0] if isinstance(nsl, list) and nsl else ""
            cluster_list = task.context.get("clusters", [])
            cluster = cluster_list[0] if cluster_list else "infra01"
            if len(cluster) <= 8:
                known = list(self.store.cluster_stats.keys())
                cluster = known[0] if known else "infra01"
            if not ns:
                return

            if task.task_type in ("root_cause_analysis", "cross_cluster_correlation"):
                all_signals = task.context.get("signals", [])
                signal_count = task.context.get("signal_count", len(all_signals))

                inc = mgr.process_signal(
                    namespace=ns, cluster_id=cluster,
                    signal_type=task.context.get("finding_type", "namespace_correlation"),
                    severity=task.context.get("severity", "high"),
                    signal_id=str(task.task_id)[:8],
                    resource_name=f"{signal_count} correlated signals",
                )

                # Append all correlated signals from the finding evidence
                for sig in all_signals:
                    if isinstance(sig, dict):
                        mgr.process_signal(
                            namespace=ns, cluster_id=cluster,
                            signal_type=sig.get("signal_type", sig.get("type", "unknown")),
                            severity=sig.get("severity", "medium"),
                            signal_id=sig.get("signal_id", str(hash(str(sig)))[:8]),
                            resource_name=sig.get("resource_name", sig.get("resource", "")),
                        )

                # Attach RCA output
                mgr.add_inference(namespace=ns, cluster_id=cluster,
                                  task_type="root_cause_analysis", model=model, output=output)

                # Parse structured RCA output for classification + remediation
                parsed = None
                try:
                    import re
                    cleaned = re.sub(r'<think>.*?</think>', '', output, flags=re.DOTALL)
                    cleaned = cleaned.replace('```json', '').replace('```', '').strip()
                    start = cleaned.find("{")
                    if start >= 0:
                        json_str = cleaned[start:]
                        try:
                            parsed = _json.loads(json_str)
                        except _json.JSONDecodeError:
                            opens = json_str.count("{") - json_str.count("}")
                            json_str += "}" * max(opens, 0)
                            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                            parsed = _json.loads(json_str)
                except (ValueError, _json.JSONDecodeError):
                    pass

                if parsed:
                    if parsed.get("category"):
                        mgr.add_classification(
                            namespace=ns, cluster_id=cluster,
                            failure_class=str(parsed["category"]),
                            confidence=float(parsed.get("confidence", 0.7)),
                            model=model,
                        )
                    rem = parsed.get("remediation", {})
                    if isinstance(rem, dict):
                        for step in rem.get("steps", []):
                            mgr.add_remediation_option(
                                namespace=ns, cluster_id=cluster,
                                action=step, risk=str(rem.get("risk", "medium")), source="rca",
                            )
                        for cmd in rem.get("commands", []):
                            mgr.add_remediation_option(
                                namespace=ns, cluster_id=cluster,
                                action=f"Run: {cmd}", command=cmd,
                                risk=str(rem.get("risk", "low")), source="rca",
                            )

            elif task.task_type == "classify_signal" and output:
                # Micro: enrich existing incident with classification (don't create new)
                try:
                    parsed = _json.loads(output.strip().strip("`").strip())
                    if parsed.get("failure_class"):
                        mgr.add_classification(
                            namespace=ns, cluster_id=cluster,
                            failure_class=parsed["failure_class"],
                            confidence=float(parsed.get("confidence", 0.5)),
                            model=model,
                        )
                except (ValueError, _json.JSONDecodeError, AttributeError):
                    pass

            elif task.task_type == "suggest_remediation" and output:
                # Micro: enrich existing incident with remediation option
                try:
                    parsed = _json.loads(output.strip().strip("`").strip())
                    if parsed.get("fix"):
                        mgr.add_remediation_option(
                            namespace=ns, cluster_id=cluster,
                            action=parsed["fix"],
                            command=parsed.get("command"),
                            risk=str(parsed.get("risk", "medium")),
                            source="micro",
                        )
                except (ValueError, _json.JSONDecodeError, AttributeError):
                    pass

            elif task.task_type == "explain_signal":
                # Micro: enrich existing incident with explanation
                mgr.add_inference(namespace=ns, cluster_id=cluster,
                                  task_type="explain_signal", model=model, output=output)

            # Phase 1 Kafka dual-write: publish incident state change
            try:
                from app.integrations.kafka_publisher import publish_incident_event
                inc_state = mgr._find_open(ns, cluster)
                if inc_state:
                    publish_incident_event({
                        "id": inc_state.get("id", ""),
                        "namespace": ns,
                        "cluster_id": cluster,
                        "status": inc_state.get("status", "open"),
                        "severity": inc_state.get("severity", ""),
                        "task_type": task.task_type,
                        "model": model,
                        "signal_count": inc_state.get("signal_count", 0),
                    })
            except Exception:
                pass

        except Exception as e:
            logger.debug("Incident feed error: %s", e)

    def _push_escalation(self, decision):
        """Log escalation for cross-product visibility. Actual push happens via Kafka/webhook."""
        pass

    # ---------- watchdog ----------
    _WATCHDOG_CHECK_INTERVAL = 30   # seconds between checks
    _HEARTBEAT_STALE_THRESHOLD = 60  # seconds before declaring thread dead

    def _persist_stats(self):
        """Flush agent stats, session totals, and snapshot to DB for persistence across restarts."""
        from app.db import enqueue_write
        try:
            agent_count = len(self.store.agent_stats)
            logger.info("Persisting stats: %d agents, totals.raw=%d", agent_count, self.totals["raw_signals"])
            for name, stats in self.store.agent_stats.items():
                enqueue_write("agent_stats_snapshots", {
                    "session_id": self.session_id,
                    "agent_name": name,
                    "total_evaluated": getattr(stats, "total_evaluated", 0),
                    "escalated": getattr(stats, "escalated", 0),
                    "kept": getattr(stats, "kept", 0),
                    "dropped": getattr(stats, "dropped", 0),
                    "suppressed": getattr(stats, "suppressed", 0),
                    "deduped": getattr(stats, "deduped", 0),
                })

            model_stats_json = {}
            for k, v in self.model_stats.items():
                model_stats_json[k] = {
                    "calls": v.get("calls", 0),
                    "avg_latency": round(v.get("latency_sum", 0) / max(v.get("calls", 1), 1), 1),
                    "avg_tps": round(v.get("tps_sum", 0) / max(v.get("calls", 1), 1), 1),
                }

            enqueue_write("session_snapshots", {
                "session_id": self.session_id,
                "raw_signals": self.totals["raw_signals"],
                "reasoning_tasks": self.totals["reasoning_tasks"],
                "inference_calls": self.totals["inference_calls"],
                "findings": self.totals["findings"],
                "dropped": self.totals["dropped"],
                "compression_ratio": self.metrics["compression_ratio"],
                "signals_per_second": self.metrics["signals_per_second"],
                "projected_clusters": self.metrics["projected_clusters"],
                "model_stats": model_stats_json,
            })

            enqueue_write("metrics_snapshots", {
                "session_id": self.session_id,
                "signals_per_second": self.metrics["signals_per_second"],
                "compression_ratio": self.metrics["compression_ratio"],
                "reasoning_tasks": int(self.metrics["reasoning_tasks"]),
                "projected_clusters": self.metrics["projected_clusters"],
                "avg_latency_ms": self.metrics["avg_latency_ms"],
                "avg_tps": self.metrics["avg_tps"],
                "inference_in_flight": self.metrics["inference_in_flight"],
            })
        except Exception as e:
            logger.warning("Stats persistence failed: %s", e)

    def _watchdog_loop(self):
        """Monitors the process-loop heartbeat; restarts the thread if stale."""
        logger.info("_watchdog_loop STARTED")
        while not self._stop.is_set():
            self._stop.wait(self._WATCHDOG_CHECK_INTERVAL)
            if self._stop.is_set():
                break

            restart_reason = None
            with self._heartbeat_lock:
                stale = time.monotonic() - self._last_heartbeat

            thread_alive = self._processor_thread.is_alive() if self._processor_thread else False

            if stale > self._HEARTBEAT_STALE_THRESHOLD:
                restart_reason = (
                    f"heartbeat stale ({stale:.1f}s > {self._HEARTBEAT_STALE_THRESHOLD}s), "
                    f"thread.is_alive={thread_alive}"
                )
            elif not thread_alive:
                restart_reason = "thread dead (is_alive=False)"

            if restart_reason:
                self._process_loop_restarts += 1
                logger.error(
                    "WATCHDOG: process loop %s — restarting "
                    "(previous restarts=%d)",
                    restart_reason, self._process_loop_restarts,
                )
                import sys, traceback
                for thread_id, frame in sys._current_frames().items():
                    if thread_id != threading.get_ident():
                        stack = "".join(traceback.format_stack(frame))
                        if "process_loop" in stack or "deepfield-processor" in stack.lower():
                            logger.error("STUCK THREAD STACK:\n%s", stack)
                t = threading.Thread(
                    target=self._process_loop, daemon=True,
                    name=f"deepfield-processor-r{self._process_loop_restarts}",
                )
                self._processor_thread = t
                t.start()
        logger.info("_watchdog_loop EXITED")

    def _log_event(self, tier: str, action: str, data: dict):
        from datetime import datetime, timezone
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tier": tier,
            "action": action,
            **data,
        }
        with self._lock:
            self.agent_log.append(event)
            if len(self.agent_log) > 50:
                self.agent_log = self.agent_log[-50:]

    _TASK_TO_PROMPT = {
        "root_cause_analysis": "rca",
        "summarize_finding": "triage",
        "cross_cluster_correlation": "correlation",
        "fleet_summary": "rca",
        "incident_analysis": "incident",
        # Micro-tier task types
        "classify_signal": "classify_signal",
        "correlate_findings": "correlate_findings",
        "suggest_remediation": "suggest_remediation",
        "explain_signal": "explain_signal",
        "filter_noise": "filter_noise",
    }

    def _do_inference(self, task, model):
        """Execute a single inference call and update metrics."""
        task_type = getattr(task, 'task_type', '')
        from app.agents.prompts import load_prompt
        prompt_name = self._TASK_TO_PROMPT.get(task_type, "rca")
        prompt_config = load_prompt(prompt_name)
        max_tokens = prompt_config.get("max_tokens", 800)
        resp = self.client.infer(model=model, prompt=task.prompt, max_tokens=max_tokens)
        import re as _re
        if resp.output:
            resp.output = _re.sub(r'<think>.*?</think>', '', resp.output, flags=_re.DOTALL).strip()
        tier = "micro" if "cpu" in model or "granite" in model or "phi3" in model or "qwen25" in model else "macro"
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
                    self.model_stats[model] = {"calls": 0, "latency_sum": 0, "tps_sum": 0, "in_flight": 0, "errors": 0}
                self.model_stats[model]["calls"] += 1
                self.model_stats[model]["latency_sum"] += resp.latency_ms
                self.model_stats[model]["tps_sum"] += resp.tokens_per_second

                self.live_inference = {
                    "last_model": model,
                    "last_latency_ms": round(resp.latency_ms, 1),
                    "in_flight": self.metrics["inference_in_flight"],
                    "completed": self.metrics["inference_completed"],
                }

                self.store.add_inference({
                    "model": model, "tier": tier, "task_type": task.task_type,
                    "prompt": task.prompt, "output": resp.output or "",
                    "latency_ms": round(resp.latency_ms, 1),
                    "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out,
                    "severity": task.context.get("severity", ""),
                    "finding_type": task.context.get("finding_type", ""),
                })
                self._log_event(tier, "inference_complete", {
                    "model": model, "task_type": task.task_type,
                    "latency_ms": round(resp.latency_ms, 1),
                    "tokens": resp.tokens_out,
                    "output": resp.output[:200] if resp.output else "",
                    "severity": task.context.get("severity", ""),
                })
                self._feed_incident(task, model, resp.output or "")
            else:
                self.totals["inference_calls"] += 1
                if model not in self.model_stats:
                    self.model_stats[model] = {"calls": 0, "latency_sum": 0, "tps_sum": 0, "in_flight": 0, "errors": 0}
                self.model_stats[model]["calls"] += 1
                self.model_stats[model]["errors"] = self.model_stats[model].get("errors", 0) + 1
                self.store.add_inference({
                    "model": model, "tier": tier, "task_type": task.task_type,
                    "prompt": task.prompt, "output": "", "error": resp.error or "unknown",
                    "latency_ms": round(resp.latency_ms, 1), "tokens_in": 0, "tokens_out": 0,
                })
                self._log_event(tier, "inference_error", {
                    "model": model, "error": resp.error[:200] if resp.error else "unknown",
                })

    def _take_snapshot(self):
        """Record a time-series snapshot."""
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
        # Non-blocking read — may be slightly stale, but won't deadlock
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
                "agent_log": list(self.agent_log[-30:]),
                "snapshots": self.snapshots[-20:],
                "queue_depth": len(self._signal_queue),
                "processor_alive": self._processor_thread.is_alive() if self._processor_thread else False,
                "process_loop_restarts": self._process_loop_restarts,
            }
        except Exception:
            return {"session_id": self.session_id, "status": self.status, "metrics": dict(self.metrics), "totals": self.totals, "agent_log": [], "snapshots": [], "model_stats": {}, "live_inference": {}, "queue_depth": 0}


def create_streaming_session(client=None, seed=42, source="synthetic", cluster_configs=None, scan_interval=30):
    import uuid
    sid = str(uuid.uuid4())
    s = StreamingSession(sid, client=client, seed=seed, source=source, cluster_configs=cluster_configs, scan_interval=scan_interval)
    _sessions[sid] = s
    return s


def get_streaming_session(session_id: str):
    return _sessions.get(session_id)
