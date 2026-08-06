"""Bridge between deepfield's signal flow and the cascade framework.

Runs the cascade pipeline in shadow mode alongside deepfield's existing
nanoagent pipeline. Compares decisions, logs disagreements, and feeds
the promotion engine with real production data.

Usage:
    from app.cascade_bridge import CascadeBridge

    bridge = CascadeBridge()
    # After normalize_batch():
    bridge.process(normalized_signals, deepfield_decisions)
    # Periodically:
    bridge.run_promotion_round()
    bridge.get_rubric()
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

from app.domain.models import FilterDecision, NormalizedSignal

try:
    from intel_inference_router.cascade import (
        CascadePipeline,
        Signal,
    )
    from intel_inference_router.cascade.agents import default_agents
    from intel_inference_router.cascade.promotion import (
        AgentMetrics,
        Baseline,
        PromotionEngine,
        RuleAgent,
    )
    from intel_inference_router.cascade.corpus_analyzer import CorpusAnalyzer
    from intel_inference_router.cascade.dynamic_agents import RepeatFloodSuppressor, DominantNoiseSuppressor
    from app.cascade_store import (
        log_decisions, log_promotion, log_gate_fire, save_state, load_latest_state
    )
    _HAS_CASCADE = True
except ImportError:
    _HAS_CASCADE = False

log = logging.getLogger(__name__)


@dataclass
class BridgeStats:
    """Running statistics for the cascade bridge."""
    signals_processed: int = 0
    cascade_handled: int = 0
    cascade_forwarded: int = 0
    agreements: int = 0
    disagreements: int = 0
    false_negatives: int = 0
    compression_ratio: float = 0.0
    started_at: str = ""
    last_updated: str = ""


def _signal_to_cascade(ns: NormalizedSignal) -> "Signal":
    """Convert deepfield NormalizedSignal to cascade Signal."""
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
    """Shadow-mode bridge between deepfield and the cascade framework."""

    def __init__(self, audit_dir: Optional[str] = None):
        if not _HAS_CASCADE:
            log.warning("intel_inference_router not installed — cascade bridge disabled")
            self.enabled = False
            return

        self.enabled = True
        self.pipeline = CascadePipeline(default_agents())
        self.promotion = PromotionEngine()
        self.stats = BridgeStats(started_at=datetime.now(timezone.utc).isoformat())

        # Gate 2 (phi-4 via LiteLLM) state — classifies EXTRA_KEEP disagreements
        self._gate2_buffer: list = []
        self._gate2_max_buffer = 5000
        self._gate2_min_buffer = 100
        self._gate2_min_compression = 0.35
        self._gate2_sustain_minutes = 15
        self._gate2_max_wait_minutes = 120  # time cap: fire after 2 hours regardless
        self._gate2_stable_since: float = 0
        self._gate2_started_at: float = time.monotonic()  # for time cap
        self._gate2_last_fire = 0
        self._gate2_compression_history: list = []
        self._gate2_results: list = []
        self._gate2_running = False
        self._gate2_fire_count = 0
        self._gate2_hysteresis = 0.03  # allow 3% dip without resetting sustain

        # Gate 3 (LLM) state
        self._gate3_buffer: list = []
        self._gate3_min_encoder_signals = 100
        self._gate3_confidence_threshold = 0.70
        self._gate3_results: list = []
        self._gate3_fire_count = 0

        # Dynamic agents — activated from discovered patterns
        self._repeat_suppressor = RepeatFloodSuppressor(max_repeats=3, window_seconds=300)
        self._noise_suppressor = DominantNoiseSuppressor(window_seconds=300)
        self.pipeline.register(self._repeat_suppressor)
        self.pipeline.register(self._noise_suppressor)
        self._activated_types: set = set()

        # Corpus analyzer — discovers patterns, proposes draft agents
        self.corpus_analyzer = CorpusAnalyzer(
            min_frequency=0.05,
            min_repeat_count=10,
            repeat_window_seconds=300,
            analysis_interval=300,
        )

        # Feedback loop: signal types the cascade should never drop
        # Learned from disagreements where cascade drops but deepfield keeps
        self._never_drop_types: set = set()
        self._fn_type_counts: Dict[str, int] = defaultdict(int)
        self._fn_learn_threshold = 5  # after 5 FNs of same type, add to never-drop

        # Build baseline from observed normal ranges (starts empty, learns)
        self.baseline = Baseline(normal_ranges={})
        self._observed_ranges: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))

        # Track agent metrics for promotion
        self._agent_metrics: Dict[str, AgentMetrics] = {}
        self._agent_rules: Dict[str, RuleAgent] = {}

        # Promotion tracking
        self._promotion_log: list = []
        self._last_promotion_time: float = 0
        self._promotion_interval: float = 300  # auto-promote every 5 min

        # Disagreement log for analysis
        self._disagreements: list = []
        self._audit_dir = Path(audit_dir) if audit_dir else None
        if self._audit_dir:
            self._audit_dir.mkdir(parents=True, exist_ok=True)

        # Restore state from previous run
        self._state_path = Path(audit_dir or "/tmp/cascade-audit") / "bridge_state.json"
        self._restore_state()

    def process(
        self,
        signals: List[NormalizedSignal],
        deepfield_decisions: List[FilterDecision],
    ) -> Dict:
        """Run cascade in shadow mode alongside deepfield's decisions.

        Does NOT affect the real pipeline — only observes and compares.
        Returns comparison metrics.
        """
        if not self.enabled or not signals:
            return {"enabled": False}

        # Convert to cascade signals
        cascade_signals = [_signal_to_cascade(s) for s in signals]

        # Apply learned never-drop overrides before running cascade
        # Never-drop signals are protected from ALL agents (severity gate + dynamic)
        protected_ids = set()
        for s in cascade_signals:
            fn_key = f"{s.signal_type}:{s.severity}"
            if fn_key in self._never_drop_types:
                protected_ids.add(s.signal_id)
                s.labels["_protected"] = "never_drop"
                if s.severity == "info":
                    s.severity = "low"

        # Run cascade pipeline
        t0 = time.monotonic()
        cascade_result = self.pipeline.run(cascade_signals)
        cascade_ms = (time.monotonic() - t0) * 1000

        # Re-add protected signals that were incorrectly removed by dynamic agents
        remaining_ids = {s.signal_id for s in cascade_result.remaining}
        for s in cascade_signals:
            if s.signal_id in protected_ids and s.signal_id not in remaining_ids:
                cascade_result.remaining.append(s)

        # Track compression for Gate 2 stability check
        self._gate2_compression_history.append(self.stats.compression_ratio)
        if len(self._gate2_compression_history) > 60:
            self._gate2_compression_history = self._gate2_compression_history[-60:]

        # Track when compression first crossed the threshold (with hysteresis)
        now = time.monotonic()
        if self.stats.compression_ratio >= self._gate2_min_compression:
            if self._gate2_stable_since == 0:
                self._gate2_stable_since = now
                log.info("Gate 2: compression hit %.0f%%, starting sustain timer",
                         self.stats.compression_ratio * 100)
        elif self.stats.compression_ratio < (self._gate2_min_compression - self._gate2_hysteresis):
            # Only reset if drops more than 3% below threshold (hysteresis)
            if self._gate2_stable_since > 0:
                log.info("Gate 2: compression dropped to %.0f%%, resetting sustain",
                         self.stats.compression_ratio * 100)
            self._gate2_stable_since = 0

        # Build decision maps for comparison
        df_dropped = {d.signal_id for d in deepfield_decisions
                      if d.outcome in ("drop", "suppress", "dedupe")}
        df_kept = {s.signal_id for s in signals} - df_dropped

        cascade_remaining_ids = {s.signal_id for s in cascade_result.remaining}
        cascade_dropped = {s.signal_id for s in signals} - cascade_remaining_ids

        # Buffer EXTRA_KEEP disagreements ONLY after compression hits threshold
        if self.stats.compression_ratio >= self._gate2_min_compression:
            for s in signals:
                df_drop = s.signal_id in df_dropped
                cc_keep = s.signal_id in cascade_remaining_ids
                if df_drop and cc_keep:
                    self._gate2_buffer.append({
                        "signal_id": str(s.signal_id),
                        "signal_type": s.signal_type,
                        "severity": s.severity,
                        "content": s.evidence if hasattr(s, 'evidence') else {},
                        "namespace": s.namespace,
                    })
            if len(self._gate2_buffer) > self._gate2_max_buffer:
                self._gate2_buffer = self._gate2_buffer[-self._gate2_max_buffer:]

            # Check if Gate 2 should fire
            self._maybe_fire_gate2()
        elif self._gate2_buffer:
            # Gate 2 check runs even when buffer is full (already above threshold)
            self._maybe_fire_gate2()

        # Compare decisions
        agreements = 0
        disagreements = 0
        false_negatives = 0

        for s in signals:
            df_drop = s.signal_id in df_dropped
            cc_drop = s.signal_id in cascade_dropped

            if df_drop == cc_drop:
                agreements += 1
            else:
                disagreements += 1
                disagreement = {
                    "signal_id": str(s.signal_id),
                    "signal_type": s.signal_type,
                    "severity": s.severity,
                    "namespace": s.namespace,
                    "deepfield": "drop" if df_drop else "keep",
                    "cascade": "drop" if cc_drop else "keep",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # False negative: cascade dropped something deepfield kept
                if cc_drop and not df_drop:
                    false_negatives += 1
                    disagreement["type"] = "FALSE_NEGATIVE"

                    # Feedback loop: learn from mistakes
                    fn_key = f"{s.signal_type}:{s.severity}"
                    self._fn_type_counts[fn_key] += 1
                    if self._fn_type_counts[fn_key] >= self._fn_learn_threshold:
                        if fn_key not in self._never_drop_types:
                            self._never_drop_types.add(fn_key)
                            log.info("LEARNED: never drop %s (seen %d FNs)",
                                     fn_key, self._fn_type_counts[fn_key])
                else:
                    disagreement["type"] = "EXTRA_KEEP"

                self._disagreements.append(disagreement)

        # Update baseline from observed metrics
        self._update_baseline(signals)

        # Update stats
        self.stats.signals_processed += len(signals)
        self.stats.cascade_handled += len(cascade_dropped)
        self.stats.cascade_forwarded += len(cascade_remaining_ids)
        self.stats.agreements += agreements
        self.stats.disagreements += disagreements
        self.stats.false_negatives += false_negatives
        if self.stats.signals_processed > 0:
            self.stats.compression_ratio = self.stats.cascade_handled / self.stats.signals_processed
        self.stats.last_updated = datetime.now(timezone.utc).isoformat()

        # Feed corpus analyzer
        self.corpus_analyzer.observe(cascade_signals)

        # Auto-promote + discover new agents on schedule
        now = time.monotonic()
        if now - self._last_promotion_time > self._promotion_interval:
            self._last_promotion_time = now

            # Step 1: Corpus analyzer discovers new patterns → activate dynamic agents
            new_agents = self.corpus_analyzer.maybe_analyze()
            for agent_metrics, rule in new_agents:
                self._agent_metrics[agent_metrics.name] = agent_metrics
                self._agent_rules[agent_metrics.name] = rule

                # ACTIVATE: wire discovered patterns into dynamic agents
                sig_type = agent_metrics.config.get("signal_type", "")
                pattern_type = agent_metrics.config.get("pattern_type", "")
                if sig_type and sig_type not in self._activated_types:
                    if pattern_type == "repeat_flood":
                        self._repeat_suppressor.add_signal_type(sig_type)
                        self._activated_types.add(sig_type)
                        log.info("ACTIVATED repeat suppressor for: %s", sig_type)
                    elif pattern_type == "dominant_type":
                        self._noise_suppressor.add_noise_type(sig_type)
                        self._activated_types.add(sig_type)
                        log.info("ACTIVATED noise suppressor for: %s", sig_type)

                self._promotion_log.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "activated" if sig_type in self._activated_types else "discovered",
                    "agent": agent_metrics.name,
                    "tier": "draft",
                    "status": "active" if sig_type in self._activated_types else "new",
                    "accuracy": 0,
                    "samples": 0,
                    "config": agent_metrics.config,
                })
                log.info("Corpus analyzer: %s (%s) — %s",
                         agent_metrics.name, pattern_type,
                         "ACTIVATED" if sig_type in self._activated_types else "discovered")

            # Step 1.5: Check for human approval trigger
            trigger_path = Path(self._audit_dir or "/tmp/cascade-audit") / "approve_micro"
            if trigger_path.exists():
                approved_count = 0
                for name, metrics in self._agent_metrics.items():
                    # Force-promote through nano → micro for agents with enough evidence
                    if metrics.samples_tested >= 200 and metrics.accuracy >= 0.75:
                        if metrics.tier in ("draft", "candidate"):
                            metrics.tier = "nano"
                        if metrics.samples_tested >= 500 and metrics.accuracy >= 0.85:
                            metrics.human_reviewed = True
                            metrics.tier = "micro"
                            approved_count += 1
                        self._promotion_log.append({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "event": "human_approved",
                            "agent": name,
                            "tier": metrics.tier,
                            "status": "promoted",
                            "accuracy": metrics.accuracy,
                            "samples": metrics.samples_tested,
                        })
                trigger_path.unlink()
                if approved_count:
                    log.info("HUMAN APPROVED: %d agents promoted to micro", approved_count)
                self._save_state()

            # Step 2: Promote existing agents
            promo = self.run_promotion_round()
            if promo.get("agents"):
                for a in promo["agents"]:
                    self._promotion_log.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event": "promoted",
                        "agent": a["name"],
                        "tier": a["tier"],
                        "status": a["status"],
                        "accuracy": a["accuracy"],
                        "samples": a["samples"],
                    })
                log.info("Auto-promotion: %s", {a["name"]: a["tier"] for a in promo["agents"]})

            # Step 3: Save state
            self._save_state()

        # Persist audit log periodically
        if self._audit_dir and len(self._disagreements) % 100 == 0 and self._disagreements:
            self._flush_audit()

        return {
            "enabled": True,
            "signals": len(signals),
            "cascade_ms": round(cascade_ms, 1),
            "cascade_compression": round(cascade_result.compression_ratio, 3),
            "agreements": agreements,
            "disagreements": disagreements,
            "false_negatives": false_negatives,
            "deepfield_compression": round(len(df_dropped) / len(signals), 3) if signals else 0,
            "encoder_classifications": len(encoder_results),
        }

    def _update_baseline(self, signals: List[NormalizedSignal]):
        """Learn normal ranges from observed signal metrics."""
        for s in signals:
            for key, val in s.evidence.items():
                if isinstance(val, (int, float)):
                    self._observed_ranges[s.signal_type][key].append(val)

        # Recompute baselines every 1000 observations
        total_obs = sum(len(v) for vals in self._observed_ranges.values() for v in vals.values())
        if total_obs > 0 and total_obs % 1000 == 0:
            for sig_type, features in self._observed_ranges.items():
                ranges = {}
                for key, values in features.items():
                    if len(values) >= 50:
                        sorted_vals = sorted(values)
                        p5 = sorted_vals[int(len(sorted_vals) * 0.05)]
                        p95 = sorted_vals[int(len(sorted_vals) * 0.95)]
                        ranges[key] = {"low": p5, "high": p95}
                if ranges:
                    self.baseline.normal_ranges[sig_type] = ranges
            log.info("Baseline updated: %d signal types, %d total observations",
                     len(self.baseline.normal_ranges), total_obs)

    def run_promotion_round(self) -> Dict:
        """Run agent promotion using observed data."""
        if not self.enabled:
            return {"enabled": False}

        # Build signals from observed ranges for validation
        validation_signals = []
        for sig_type, features in self._observed_ranges.items():
            for key, values in features.items():
                for v in values[-100:]:  # last 100 observations
                    validation_signals.append({
                        "signal_type": sig_type,
                        "features": {key: v},
                    })

        if not validation_signals:
            return {"no_data": True}

        # Validate ALL known agents — both pipeline agents and discovered ones
        agents = []
        rules = []

        # Built-in pipeline agents
        for agent in self.pipeline._agents:
            name = agent.name
            if name not in self._agent_metrics:
                self._agent_metrics[name] = AgentMetrics(name=name, tier="draft")
                self._agent_rules[name] = RuleAgent({
                    "name": name,
                    "condition": {"field": "cpu_percent", "operator": "gt", "value": 95},
                })

        # Include ALL agents (built-in + discovered)
        for name, metrics in self._agent_metrics.items():
            if name in self._agent_rules:
                agents.append(metrics)
                rules.append(self._agent_rules[name])

        if not agents:
            return {"no_agents": True}

        results = self.promotion.run_validation_round(
            agents, rules, validation_signals, self.baseline
        )

        # Update stored metrics and log promotions
        for r in results:
            old_tier = self._agent_metrics.get(r.name, AgentMetrics()).tier
            self._agent_metrics[r.name] = r
            if r.tier != old_tier and old_tier != r.tier:
                log.info("Agent %s promoted: %s → %s (acc=%.1f%%)", r.name, old_tier, r.tier, r.accuracy * 100)

        return self.promotion.rubric_matrix(results)

    def get_stats(self) -> Dict:
        """Return current bridge statistics."""
        return asdict(self.stats)

    def get_rubric(self) -> Dict:
        """Return the current rubric matrix for all agents."""
        return self.promotion.rubric_matrix(list(self._agent_metrics.values()))

    def approve_for_micro(self) -> Dict:
        """Human approval: directly promote eligible agents to micro tier."""
        promoted = []
        for name, metrics in self._agent_metrics.items():
            if metrics.samples_tested >= 200 and metrics.tier in ("draft", "candidate", "nano"):
                old_tier = metrics.tier
                metrics.human_reviewed = True
                metrics.tier = "micro"
                metrics.rubric_status = "green"
                promoted.append(name)
                metrics.promotion_history.append({
                    "from": old_tier, "to": "micro",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "accuracy": round(metrics.accuracy, 4),
                    "samples": metrics.samples_tested,
                })
                self._promotion_log.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "human_promoted_to_micro",
                    "agent": name, "tier": "micro", "status": "green",
                    "accuracy": metrics.accuracy, "samples": metrics.samples_tested,
                })
                log.info("PROMOTED TO MICRO: %s (%s → micro)", name, old_tier)
        if promoted:
            self._save_state()
        return {
            "promoted_to_micro": len(promoted),
            "agents": promoted,
            "rubric": self.promotion.rubric_matrix(list(self._agent_metrics.values())),
        }

    def _is_gate1_stable(self) -> bool:
        """Check if Gate 1 compression has sustained above threshold."""
        if self._gate2_stable_since == 0:
            return False
        elapsed = time.monotonic() - self._gate2_stable_since
        return elapsed >= self._gate2_sustain_minutes * 60

    def _gate1_sustain_progress(self) -> float:
        """Return 0-100% progress toward Gate 1 sustain requirement."""
        if self._gate2_stable_since == 0:
            return 0.0
        elapsed = time.monotonic() - self._gate2_stable_since
        return min(100.0, (elapsed / (self._gate2_sustain_minutes * 60)) * 100)

    def _maybe_fire_gate2(self):
        """Check if Gate 2 should fire — sustain threshold OR time cap."""
        if self._gate2_running:
            return

        time_elapsed = time.monotonic() - self._gate2_started_at
        time_cap_hit = time_elapsed >= self._gate2_max_wait_minutes * 60

        should_fire = (
            len(self._gate2_buffer) >= self._gate2_min_buffer
            and (self._is_gate1_stable() or time_cap_hit)
        )

        if time_cap_hit and not self._is_gate1_stable() and len(self._gate2_buffer) >= self._gate2_min_buffer:
            log.info("Gate 2: TIME CAP hit (%.0f min) — firing regardless of sustain", time_elapsed / 60)

        if should_fire:
            self._gate2_last_fire = now
            self._gate2_fire_count += 1
            import threading
            batch = list(self._gate2_buffer)
            self._gate2_buffer = []
            log.info("GATE 2 FIRING: %d signals, compression stable at %.1f%%",
                     len(batch), self.stats.compression_ratio * 100)
            threading.Thread(target=self._run_gate2, args=(batch,), daemon=True).start()

    def _run_gate2(self, signals):
        """Gate 2: phi-4 classifies EXTRA_KEEP disagreements, feeds back to cascade."""
        self._gate2_running = True
        try:
            import httpx, os
            from collections import Counter

            API = os.getenv("LITELLM_API_BASE", "")
            KEY = os.getenv("LITELLM_API_KEY", "")
            MODEL = "microsoft-phi-4"

            SYS_PROMPT = """You are classifying Kubernetes signals on a demo/sandbox platform where student namespaces (sandbox-*) frequently have crashlooping pods, resource issues, and misconfigurations. This is NORMAL for this environment.

Classify as exactly one of:
- routine_noise: expected on this platform, safe to suppress
- known_pattern: seen before, low priority
- needs_attention: unusual for this environment, investigate
- real_incident: critical, affects platform stability

Answer with one word only."""

            classified = 0
            noise_patterns = Counter()
            needs_attention = []
            client = httpx.Client(timeout=60, verify=False)

            for sig in signals:
                text = f"{sig['signal_type']} {sig['severity']}: {sig.get('content', {}).get('message', '')} namespace={sig.get('namespace', '')}"

                try:
                    t0 = time.monotonic()
                    r = client.post(f"{API}/v1/chat/completions", json={
                        "model": MODEL,
                        "messages": [{"role": "system", "content": SYS_PROMPT},
                                     {"role": "user", "content": text}],
                        "max_tokens": 5,
                    }, headers={"Authorization": f"Bearer {KEY}"})
                    ms = (time.monotonic() - t0) * 1000

                    ans = r.json()["choices"][0]["message"]["content"].strip().lower()
                    classified += 1

                    entry = {
                        "signal_type": sig["signal_type"],
                        "classification": ans,
                        "confidence": 1.0,  # phi-4 is decisive, no score
                        "latency_ms": round(ms),
                    }
                    self._gate2_results.append(entry)
                    if len(self._gate2_results) > 1000:
                        self._gate2_results = self._gate2_results[-1000:]

                    if "routine_noise" in ans or "known_pattern" in ans:
                        noise_patterns[sig["signal_type"]] += 1
                    elif "needs_attention" in ans or "real_incident" in ans:
                        needs_attention.append({**sig, "classification": ans})

                except Exception as e:
                    log.debug("phi-4 call failed: %s", str(e)[:60])

            client.close()

            # Feed back: phi-4 confirmed noise → new nano agents
            for sig_type, count in noise_patterns.most_common(10):
                if count >= 3:
                    if sig_type not in self._activated_types:
                        self._repeat_suppressor.add_signal_type(sig_type)
                        self._activated_types.add(sig_type)
                        self._promotion_log.append({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "event": "phi4_feedback",
                            "agent": f"suppress_{sig_type}",
                            "tier": "nano",
                            "status": "activated_from_phi4",
                            "accuracy": 0,
                            "samples": count,
                            "config": {"signal_type": sig_type, "phi4_confirmed_noise": count},
                        })
                        log.info("PHI-4 FEEDBACK → new nano agent: suppress_%s (%d confirmed noise)",
                                 sig_type, count)

            # needs_attention signals → Gate 3 buffer
            self._gate3_buffer.extend(needs_attention)
            if len(self._gate3_buffer) > 500:
                self._gate3_buffer = self._gate3_buffer[-500:]

            noise_total = sum(noise_patterns.values())
            log.info("GATE 2 COMPLETE (phi-4): %d/%d classified, %d noise, %d needs_attention → Gate 3 (%d)",
                     classified, len(signals), noise_total, len(needs_attention), len(self._gate3_buffer))

            log_gate_fire("gate2_phi4", len(signals), classified, len(needs_attention), dict(noise_patterns))

            if len(self._gate3_buffer) >= self._gate3_min_encoder_signals:
                self._gate3_fire_count += 1
                self._gate3_results.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "buffered": len(self._gate3_buffer),
                    "status": "ready_for_deeper_analysis",
                })

        except Exception as e:
            log.warning("Gate 2 error: %s", e)
        finally:
            self._gate2_running = False

    def get_gate_status(self) -> Dict:
        """Return status of all gates."""
        sustained = self._is_gate1_stable()
        sustain_pct = self._gate1_sustain_progress()
        above_threshold = self.stats.compression_ratio >= self._gate2_min_compression

        time_elapsed = time.monotonic() - self._gate2_started_at
        time_cap_pct = min(100, (time_elapsed / (self._gate2_max_wait_minutes * 60)) * 100)

        if self._gate2_running:
            g2_status = "classifying_phi4"
        elif (sustained or time_cap_pct >= 100) and len(self._gate2_buffer) >= self._gate2_min_buffer:
            g2_status = "ready_to_fire"
        elif above_threshold:
            g2_status = f"sustaining ({sustain_pct:.0f}%)"
        else:
            g2_status = f"waiting (time cap {time_cap_pct:.0f}%)"

        return {
            "gate1_cascade": {
                "status": "running",
                "signals_processed": self.stats.signals_processed,
                "compression": round(self.stats.compression_ratio * 100, 1),
                "stable": sustained,
                "above_threshold": above_threshold,
                "sustain_progress": round(sustain_pct, 1),
                "sustain_minutes": self._gate2_sustain_minutes,
                "min_compression": round(self._gate2_min_compression * 100),
            },
            "gate2_encoder": {
                "status": g2_status,
                "buffer_size": len(self._gate2_buffer),
                "buffer_type": "EXTRA_KEEP disagreements only",
                "threshold": self._gate2_min_buffer,
                "max_buffer": self._gate2_max_buffer,
                "fires": self._gate2_fire_count,
                "classified": len(self._gate2_results),
                "ready": sustained and len(self._gate2_buffer) >= self._gate2_min_buffer,
                "gate1_stable": sustained,
                "last_results": self._gate2_results[-5:] if self._gate2_results else [],
            },
            "gate3_llm": {
                "status": "ready" if len(self._gate3_buffer) >= self._gate3_min_encoder_signals else "waiting",
                "buffer_size": len(self._gate3_buffer),
                "threshold": self._gate3_min_encoder_signals,
                "fires": self._gate3_fire_count,
                "confidence_threshold": self._gate3_confidence_threshold,
            },
        }

    def get_discovered_agents(self) -> list:
        """Return agents discovered by the corpus analyzer."""
        if hasattr(self, 'corpus_analyzer'):
            return self.corpus_analyzer.get_proposed_agents()
        return []

    def get_corpus_analysis(self) -> list:
        """Return corpus analysis log."""
        if hasattr(self, 'corpus_analyzer'):
            return self.corpus_analyzer.get_analysis_log()
        return []

    def get_promotion_log(self, limit: int = 50) -> list:
        """Return recent promotion events."""
        return self._promotion_log[-limit:]

    def get_disagreements(self, limit: int = 50) -> list:
        """Return recent disagreements between cascade and deepfield."""
        return self._disagreements[-limit:]

    def _save_state(self):
        """Persist bridge state to Postgres."""
        try:
            state = {
                "agent_metrics": {
                    name: {"name": m.name, "tier": m.tier, "samples_tested": m.samples_tested,
                           "accuracy": m.accuracy, "false_positive_rate": m.false_positive_rate,
                           "false_negative_rate": m.false_negative_rate, "rubric_status": m.rubric_status,
                           "promotion_history": m.promotion_history, "config": m.config}
                    for name, m in self._agent_metrics.items()
                },
                "agent_rules": {
                    name: {"name": r.name, "condition": r.condition, "classification": r.classification}
                    for name, r in self._agent_rules.items()
                },
                "known_patterns": list(self.corpus_analyzer._known_patterns),
                "baseline": self.baseline.normal_ranges,
                "never_drop_types": list(self._never_drop_types),
                "activated_types": list(self._activated_types),
                "fn_type_counts": dict(self._fn_type_counts),
                "stats_snapshot": {
                    "signals_processed": self.stats.signals_processed,
                    "false_negatives": self.stats.false_negatives,
                },
            }
            save_state("bridge_state", state)
        except Exception as e:
            log.warning("Failed to save state: %s", e)

    def _restore_state(self):
        """Restore state from Postgres."""
        try:
            state = load_latest_state("bridge_state")
            if not state:
                return

            for name, data in state.get("agent_metrics", {}).items():
                self._agent_metrics[name] = AgentMetrics(
                    name=data["name"], tier=data["tier"],
                    samples_tested=data.get("samples_tested", 0),
                    accuracy=data.get("accuracy", 0),
                    false_positive_rate=data.get("false_positive_rate", 0),
                    false_negative_rate=data.get("false_negative_rate", 0),
                    rubric_status=data.get("rubric_status", "red"),
                    promotion_history=data.get("promotion_history", []),
                    config=data.get("config", {}),
                )

            for name, data in state.get("agent_rules", {}).items():
                self._agent_rules[name] = RuleAgent(data)

            self.corpus_analyzer._known_patterns = set(state.get("known_patterns", []))
            self.baseline.normal_ranges = state.get("baseline", {})
            self._never_drop_types = set(state.get("never_drop_types", []))
            self._fn_type_counts = defaultdict(int, state.get("fn_type_counts", {}))
            self._activated_types = set(state.get("activated_types", []))
            for sig_type in self._activated_types:
                self._repeat_suppressor.add_signal_type(sig_type)
                self._noise_suppressor.add_noise_type(sig_type)

            log.info("Restored from Postgres: %d agents, %d patterns, %d never-drop, %d activated",
                     len(self._agent_metrics), len(self.corpus_analyzer._known_patterns),
                     len(self._never_drop_types), len(self._activated_types))
        except Exception as e:
            log.warning("Failed to restore state: %s", e)

    def _flush_audit(self):
        """Write disagreements to audit file."""
        if not self._audit_dir or not self._disagreements:
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._audit_dir / f"disagreements_{ts}.json"
        with open(path, "w") as f:
            json.dump(self._disagreements[-1000:], f, indent=2)
        log.info("Audit log flushed: %d disagreements to %s", len(self._disagreements), path)
