"""Cascade bridge — continuous signal processing pipeline.

Cascade (pattern matching) + phi-4 (classification) run together.
No staging, no gates, no comparison with deepfield.
The cascade decides, phi-4 validates, humans review the hard cases.
"""

import json
import logging
import os
import random
import time
import threading
from collections import defaultdict, Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.domain.models import FilterDecision, NormalizedSignal

try:
    from intel_inference_router.cascade import CascadePipeline, Signal
    from intel_inference_router.cascade.agents import default_agents
    from intel_inference_router.cascade.corpus_analyzer import CorpusAnalyzer
    from intel_inference_router.cascade.dynamic_agents import RepeatFloodSuppressor, DominantNoiseSuppressor
    from intel_inference_router.cascade.promotion import AgentMetrics, Baseline, PromotionEngine, RuleAgent
    from app.cascade_store import log_decisions, log_promotion, log_gate_fire, save_state, load_latest_state
    _HAS_CASCADE = True
except ImportError:
    _HAS_CASCADE = False

log = logging.getLogger(__name__)

LITELLM_API = os.getenv("LITELLM_API_BASE", "")
LITELLM_KEY = os.getenv("LITELLM_API_KEY", "")
PHI4_MODEL = os.getenv("CASCADE_LLM_MODEL", "microsoft-phi-4")

PHI4_SYSTEM = os.getenv("CASCADE_K8S_PROMPT", """You are classifying Kubernetes signals on a demo/sandbox platform. Student namespaces (sandbox-*) constantly have crashlooping pods, probe failures, image pull errors, deprecated API warnings, and pending pods. These are routine on this platform. Suppress them.

Only flag signals that indicate real platform problems: node failures, control plane issues, storage outages, network partitions, or patterns affecting multiple namespaces simultaneously.

Classify as exactly one of: routine_noise, known_pattern, needs_attention, real_incident. Answer with one word only.""")


@dataclass
class BridgeStats:
    signals_processed: int = 0
    cascade_handled: int = 0
    cascade_forwarded: int = 0
    phi4_classified: int = 0
    phi4_noise: int = 0
    phi4_important: int = 0
    compression_ratio: float = 0.0
    started_at: str = ""
    last_updated: str = ""


def _signal_to_cascade(ns: NormalizedSignal) -> Signal:
    return Signal(
        signal_id=ns.signal_id,
        signal_type=ns.signal_type,
        severity=ns.severity,
        source=ns.resource_name,
        namespace=ns.namespace,
        cluster=str(ns.cluster_id)[:8],
        content={
            "resource_kind": ns.resource_kind,
            "message": ns.evidence.get("message", ""),
            **{k: v for k, v in ns.evidence.items() if k != "message"},
            **ns.labels,
        },
        labels=ns.labels,
    )


class CascadeBridge:
    def __init__(self, audit_dir: Optional[str] = None):
        if not _HAS_CASCADE:
            log.warning("intel_inference_router not installed — cascade bridge disabled")
            self.enabled = False
            return

        self.enabled = True
        self.pipeline = CascadePipeline(default_agents())
        self.promotion = PromotionEngine()
        self.stats = BridgeStats(started_at=datetime.now(timezone.utc).isoformat())

        # Dynamic agents
        self._repeat_suppressor = RepeatFloodSuppressor(max_repeats=3, window_seconds=300)
        self._noise_suppressor = DominantNoiseSuppressor(window_seconds=300)
        self.pipeline.register(self._repeat_suppressor)
        self.pipeline.register(self._noise_suppressor)
        self._activated_types: set = set()
        self._activated_patterns: Dict[str, str] = {}
        self._activation_timestamps: Dict[str, str] = {}

        # Corpus analyzer
        self.corpus_analyzer = CorpusAnalyzer(
            min_frequency=0.05, min_repeat_count=10,
            repeat_window_seconds=300, analysis_interval=300,
        )

        # phi-4 validation — runs continuously on cascade pass-throughs
        self._phi4_buffer: list = []
        self._phi4_max_buffer = 500
        self._phi4_results: list = []
        self._phi4_running = False
        self._phi4_noise_counts: Dict[str, int] = defaultdict(int)

        # Promotion tracking
        self._agent_metrics: Dict[str, AgentMetrics] = {}
        self._agent_rules: Dict[str, RuleAgent] = {}
        self._promotion_log: list = []
        self._last_promotion_time: float = 0
        self._promotion_interval: float = 300

        # FN observation + demotion
        self._fn_count = 0
        self._fn_evaluated = 0
        self._fn_types: Dict[str, int] = defaultdict(int)

        # Shadow validation
        self._shadow_sample_rate = float(os.getenv("CASCADE_SHADOW_RATE", "0.05"))
        self._shadow_buffer: list = []
        self._shadow_running = False
        self._shadow_checks = 0
        self._shadow_demotions = 0

        # TTL + GCL verdict polling
        self._activation_ttl_hours = float(os.getenv("CASCADE_ACTIVATION_TTL_HOURS", "72"))
        self._verdict_watermark: str = ""
        self._verdict_poll_running = False

        # Baseline
        self.baseline = Baseline(normal_ranges={})
        self._observed_ranges: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))

        # Restore from Postgres
        self._restore_state()

    def process(self, signals: List[NormalizedSignal], deepfield_decisions: List[FilterDecision]) -> Dict:
        if not self.enabled or not signals:
            return {"enabled": False}

        cascade_signals = [_signal_to_cascade(s) for s in signals]

        # Run cascade
        t0 = time.monotonic()
        cascade_result = self.pipeline.run(cascade_signals)
        cascade_ms = (time.monotonic() - t0) * 1000

        # Update stats
        remaining_count = len(cascade_result.remaining)
        handled_count = len(signals) - remaining_count
        self.stats.signals_processed += len(signals)
        self.stats.cascade_handled += handled_count
        self.stats.cascade_forwarded += remaining_count
        if self.stats.signals_processed > 0:
            self.stats.compression_ratio = self.stats.cascade_handled / self.stats.signals_processed
        self.stats.last_updated = datetime.now(timezone.utc).isoformat()

        # Feed corpus analyzer
        self.corpus_analyzer.observe(cascade_signals)

        # Shadow validation: sample suppressed signals for LLM re-check
        if self._activated_types and self._shadow_sample_rate > 0 and LITELLM_API:
            self._queue_shadow_samples(cascade_result, cascade_signals)

        # Buffer pass-throughs for phi-4 validation
        for sig in cascade_result.remaining:
            self._phi4_buffer.append({
                "signal_type": sig.signal_type,
                "severity": sig.severity,
                "namespace": sig.namespace,
                "content": sig.content,
            })
        if len(self._phi4_buffer) > self._phi4_max_buffer:
            self._phi4_buffer = self._phi4_buffer[-self._phi4_max_buffer:]

        # Run phi-4 continuously in background (non-blocking)
        if self._phi4_buffer and not self._phi4_running and LITELLM_API:
            batch = list(self._phi4_buffer[:50])  # classify 50 at a time
            self._phi4_buffer = self._phi4_buffer[50:]
            threading.Thread(target=self._run_phi4, args=(batch,), daemon=True).start()

        # Shadow LLM re-check
        if self._shadow_buffer and not self._shadow_running and LITELLM_API:
            batch = list(self._shadow_buffer[:20])
            self._shadow_buffer = self._shadow_buffer[20:]
            threading.Thread(target=self._run_shadow_phi4, args=(batch,), daemon=True).start()

        # Auto-promote + discover on schedule
        now = time.monotonic()
        if now - self._last_promotion_time > self._promotion_interval:
            self._last_promotion_time = now

            # Discover new patterns
            new_agents = self.corpus_analyzer.maybe_analyze()
            for agent_metrics, rule in new_agents:
                sig_type = agent_metrics.config.get("signal_type", "")
                pattern_type = agent_metrics.config.get("pattern_type", "")
                if sig_type and sig_type not in self._activated_types:
                    # Only activate if phi-4 has confirmed this type as noise
                    if self._phi4_noise_counts.get(sig_type, 0) >= 3:
                        if pattern_type == "repeat_flood":
                            self._repeat_suppressor.add_signal_type(sig_type)
                        else:
                            self._noise_suppressor.add_noise_type(sig_type)
                        self._activated_types.add(sig_type)
                        self._activated_patterns[sig_type] = pattern_type
                        self._activation_timestamps[sig_type] = datetime.now(timezone.utc).isoformat()
                        self._promotion_log.append({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "event": "activated",
                            "agent": f"suppress_{sig_type}",
                            "tier": "nano",
                            "status": "phi4_confirmed",
                            "config": agent_metrics.config,
                        })
                        log.info("ACTIVATED: %s (phi-4 confirmed %d noise)",
                                 sig_type, self._phi4_noise_counts[sig_type])
                    else:
                        self._promotion_log.append({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "event": "discovered",
                            "agent": agent_metrics.config.get("signal_type", ""),
                            "tier": "draft",
                            "status": "awaiting_phi4_validation",
                            "config": agent_metrics.config,
                        })

            self._check_activation_ttl()
            self._save_state()

            # Poll GCL verdicts for demotion feedback
            ledger_url = os.getenv("CASCADE_LEDGER_URL", "")
            if ledger_url and not self._verdict_poll_running:
                threading.Thread(
                    target=self._poll_gcl_verdicts,
                    args=(ledger_url,), daemon=True,
                ).start()

        # Write decisions to immutable ledger (fire-and-forget)
        ledger_url = os.getenv("CASCADE_LEDGER_URL", "")
        if ledger_url and hasattr(cascade_result, "decisions") and cascade_result.decisions:
            threading.Thread(
                target=self._write_to_ledger,
                args=(ledger_url, cascade_result, cascade_signals),
                daemon=True,
            ).start()

        return {
            "enabled": True,
            "signals": len(signals),
            "cascade_ms": round(cascade_ms, 1),
            "compression": round(cascade_result.compression_ratio, 3),
        }

    def _write_to_ledger(self, ledger_url, cascade_result, cascade_signals):
        """Write decision record to immutable ledger. Matches decision-record.json schema."""
        try:
            import httpx, hashlib, json
            from uuid import uuid4

            signal_lookup = {sig.signal_id: sig for sig in cascade_signals}
            decisions = []
            for d in cascade_result.decisions:
                sig = signal_lookup.get(d.signal_id)
                decisions.append({
                    "subject_id": str(d.signal_id),
                    "subject_type": sig.signal_type if sig else "",
                    "severity": sig.severity if sig else "",
                    "namespace": sig.namespace if sig else "",
                    "outcome": d.outcome.value,
                    "agent": d.agent_name,
                    "confidence": d.confidence,
                    "tier": "nano",
                    "evidence": (d.evidence or "")[:200],
                })

            if not decisions:
                return

            batch_id = str(uuid4())
            domain = getattr(self, '_domain', 'k8s')
            record = {
                "system_id": f"cascade-{domain}",
                "batch_id": batch_id,
                "domain": domain,
                "decisions": decisions,
            }
            content = json.dumps(record, sort_keys=True, separators=(",", ":"))
            entry = {
                "entry_type": "decision.record",
                "agent_id": record["system_id"],
                "content": content,
                "content_type": "application/json",
                "source_id": record["system_id"],
                "correlation_id": batch_id,
                "idempotency_key": hashlib.sha256(f"decision.record\0{batch_id}".encode()).hexdigest(),
                "input_hash": hashlib.sha256(content.encode()).hexdigest(),
            }

            token = os.getenv("CASCADE_LEDGER_TOKEN", "")
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            client = httpx.Client(timeout=10, verify=False)
            client.post(f"{ledger_url.rstrip('/')}/api/receipts", json=entry, headers=headers)
            client.close()
        except Exception as e:
            log.debug("Ledger write failed: %s", str(e)[:60])

    def _run_phi4(self, signals):
        """Continuously validate cascade pass-throughs with phi-4."""
        self._phi4_running = True
        try:
            import httpx
            client = httpx.Client(timeout=60, verify=False)

            for sig in signals:
                text = f"{sig['signal_type']} {sig['severity']}: {sig.get('content', {}).get('message', '')} namespace={sig.get('namespace', '')}"
                try:
                    t0 = time.monotonic()
                    r = client.post(f"{LITELLM_API}/v1/chat/completions", json={
                        "model": PHI4_MODEL,
                        "messages": [{"role": "system", "content": PHI4_SYSTEM},
                                     {"role": "user", "content": text}],
                        "max_tokens": 5,
                    }, headers={"Authorization": f"Bearer {LITELLM_KEY}"})
                    ms = (time.monotonic() - t0) * 1000

                    ans = r.json()["choices"][0]["message"]["content"].strip().lower()
                    self.stats.phi4_classified += 1

                    entry = {
                        "signal_type": sig["signal_type"],
                        "classification": ans,
                        "latency_ms": round(ms),
                    }
                    self._phi4_results.append(entry)
                    if len(self._phi4_results) > 1000:
                        self._phi4_results = self._phi4_results[-1000:]

                    if "routine_noise" in ans or "known_pattern" in ans:
                        self.stats.phi4_noise += 1
                        self._phi4_noise_counts[sig["signal_type"]] += 1
                    else:
                        self.stats.phi4_important += 1

                except Exception as e:
                    log.debug("phi-4 call failed: %s", str(e)[:60])

            client.close()
        except Exception as e:
            log.warning("phi-4 error: %s", e)
        finally:
            self._phi4_running = False

    def _queue_shadow_samples(self, cascade_result, cascade_signals):
        signal_map = {s.signal_id: s for s in cascade_signals}
        candidates = []
        for d in cascade_result.decisions:
            if d.outcome.value not in ("suppress", "drop"):
                continue
            sig = signal_map.get(d.signal_id)
            if sig and sig.signal_type in self._activated_types:
                candidates.append(sig)
        if not candidates or self._shadow_sample_rate <= 0:
            return
        sample_size = max(1, int(len(candidates) * self._shadow_sample_rate))
        sample = random.sample(candidates, min(sample_size, len(candidates)))
        for sig in sample:
            self._shadow_buffer.append({
                "signal_type": sig.signal_type,
                "severity": sig.severity,
                "namespace": sig.namespace,
                "content": sig.content,
            })
        if len(self._shadow_buffer) > 100:
            self._shadow_buffer = self._shadow_buffer[-100:]

    def _run_shadow_phi4(self, signals):
        self._shadow_running = True
        try:
            import httpx
            client = httpx.Client(timeout=60, verify=False)
            for sig in signals:
                text = f"{sig['signal_type']} {sig['severity']}: {sig.get('content', {}).get('message', '')} namespace={sig.get('namespace', '')}"
                try:
                    r = client.post(f"{LITELLM_API}/v1/chat/completions", json={
                        "model": PHI4_MODEL,
                        "messages": [{"role": "system", "content": PHI4_SYSTEM},
                                     {"role": "user", "content": text}],
                        "max_tokens": 5,
                    }, headers={"Authorization": f"Bearer {LITELLM_KEY}"})
                    ans = r.json()["choices"][0]["message"]["content"].strip().lower()
                    self._shadow_checks += 1
                    if "routine_noise" not in ans and "known_pattern" not in ans:
                        self._shadow_demotions += 1
                        self._record_feedback(sig["signal_type"], is_important=True)
                        log.warning("SHADOW: LLM says '%s' is important ('%s') — demotion",
                                    sig["signal_type"], ans)
                except Exception as e:
                    log.debug("Shadow phi-4 failed: %s", str(e)[:60])
            client.close()
        except Exception as e:
            log.warning("Shadow phi-4 error: %s", e)
        finally:
            self._shadow_running = False

    def _record_feedback(self, signal_type: str, is_important: bool = False):
        self._fn_evaluated += 1
        if is_important:
            self._fn_count += 1
            self._fn_types[signal_type] += 1
            if signal_type in self._activated_types:
                self._deactivate_agent(signal_type)
                self._promotion_log.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "demoted",
                    "agent": f"suppress_{signal_type}",
                    "from_tier": "nano",
                    "to_tier": "draft",
                    "reason": f"FN confirmed: {signal_type}",
                })
                log.warning("DEMOTED: %s — FN confirmed", signal_type)

    def _deactivate_agent(self, signal_type: str):
        pattern_type = self._activated_patterns.pop(signal_type, None)
        self._activated_types.discard(signal_type)
        self._activation_timestamps.pop(signal_type, None)
        if pattern_type == "repeat_flood":
            self._repeat_suppressor.remove_signal_type(signal_type)
        elif pattern_type == "dominant_type":
            self._noise_suppressor.remove_noise_type(signal_type)

    def _check_activation_ttl(self):
        if not self._activation_timestamps or self._activation_ttl_hours <= 0:
            return
        now = datetime.now(timezone.utc)
        expired = []
        for sig_type, ts_str in list(self._activation_timestamps.items()):
            try:
                activated_at = datetime.fromisoformat(ts_str)
                age_hours = (now - activated_at).total_seconds() / 3600
                if age_hours >= self._activation_ttl_hours:
                    expired.append(sig_type)
            except (ValueError, TypeError):
                continue
        for sig_type in expired:
            self._deactivate_agent(sig_type)
            self._promotion_log.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "ttl_expired",
                "agent": f"suppress_{sig_type}",
                "reason": f"TTL expired ({self._activation_ttl_hours}h) — must re-qualify",
            })
            log.warning("TTL expired for %s — deactivated, must re-qualify", sig_type)

    def _poll_gcl_verdicts(self, ledger_url):
        self._verdict_poll_running = True
        try:
            import httpx
            token = os.getenv("CASCADE_LEDGER_TOKEN", "")
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            params = {"entry_type": "audit.verdict", "page_size": "100"}
            if self._verdict_watermark:
                params["from_ts"] = self._verdict_watermark
            client = httpx.Client(timeout=15, verify=False)
            r = client.get(f"{ledger_url.rstrip('/')}/api/entries",
                           params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            client.close()
            entries = data if isinstance(data, list) else data.get("entries", [])
            for entry in entries:
                ts = entry.get("timestamp", entry.get("created_at", ""))
                if ts and ts > self._verdict_watermark:
                    self._verdict_watermark = ts
                content = entry.get("content", "")
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        continue
                if not isinstance(content, dict) or content.get("verdict") != "FAILS":
                    continue
                signal_type = content.get("subject_type", "")
                if signal_type:
                    self._record_feedback(signal_type, is_important=True)
                    log.warning("GCL FAILS → demotion: signal_type=%s", signal_type)
            if entries:
                log.info("Polled %d verdicts, watermark=%s",
                         len(entries), self._verdict_watermark[:19])
        except Exception as e:
            log.debug("Verdict poll failed: %s", str(e)[:80])
        finally:
            self._verdict_poll_running = False

    def _save_state(self):
        try:
            state = {
                "activated_types": list(self._activated_types),
                "activated_patterns": dict(self._activated_patterns),
                "activation_timestamps": dict(self._activation_timestamps),
                "verdict_watermark": self._verdict_watermark,
                "phi4_noise_counts": dict(self._phi4_noise_counts),
                "known_patterns": list(self.corpus_analyzer._known_patterns),
                "stats_snapshot": {
                    "signals_processed": self.stats.signals_processed,
                    "phi4_classified": self.stats.phi4_classified,
                },
            }
            save_state("bridge_state", state)
        except Exception as e:
            log.warning("Failed to save state: %s", e)

    def _restore_state(self):
        try:
            state = load_latest_state("bridge_state")
            if not state:
                return
            self._activated_types = set(state.get("activated_types", []))
            self._activated_patterns = dict(state.get("activated_patterns", {}))
            self._activation_timestamps = dict(state.get("activation_timestamps", {}))
            self._verdict_watermark = state.get("verdict_watermark", "")
            self._phi4_noise_counts = defaultdict(int, state.get("phi4_noise_counts", {}))
            self.corpus_analyzer._known_patterns = set(state.get("known_patterns", []))
            for sig_type in self._activated_types:
                pattern_type = self._activated_patterns.get(sig_type, "dominant_type")
                if pattern_type == "repeat_flood":
                    self._repeat_suppressor.add_signal_type(sig_type)
                else:
                    self._noise_suppressor.add_noise_type(sig_type)
            log.info("Restored: %d activated, %d phi4 counts, %d patterns",
                     len(self._activated_types), len(self._phi4_noise_counts),
                     len(self.corpus_analyzer._known_patterns))
        except Exception as e:
            log.warning("Failed to restore state: %s", e)

    def get_stats(self) -> Dict:
        stats = asdict(self.stats)
        stats["fn_count"] = self._fn_count
        stats["fn_rate"] = round(self._fn_count / max(1, self.stats.signals_processed) * 100, 3)
        stats["fn_types"] = dict(sorted(self._fn_types.items(), key=lambda x: -x[1])[:10])
        stats["shadow_checks"] = self._shadow_checks
        stats["shadow_demotions"] = self._shadow_demotions
        stats["activation_ttl_hours"] = self._activation_ttl_hours
        return stats

    def get_phi4_results(self, limit: int = 20) -> list:
        return self._phi4_results[-limit:]

    def get_phi4_summary(self) -> Dict:
        top_noise = sorted(self._phi4_noise_counts.items(), key=lambda x: -x[1])[:10]
        return {
            "classified": self.stats.phi4_classified,
            "noise": self.stats.phi4_noise,
            "important": self.stats.phi4_important,
            "noise_pct": round(self.stats.phi4_noise / max(1, self.stats.phi4_classified) * 100, 1),
            "top_noise_types": [{
                "signal_type": k,
                "noise_count": v,
                "activated": k in self._activated_types,
            } for k, v in top_noise],
            "activated_types": list(self._activated_types),
            "buffer_size": len(self._phi4_buffer),
            "running": self._phi4_running,
        }

    def get_promotion_log(self, limit: int = 30) -> list:
        return self._promotion_log[-limit:]

    def get_discovered_agents(self) -> list:
        if hasattr(self, 'corpus_analyzer'):
            return self.corpus_analyzer.get_proposed_agents()
        return []
