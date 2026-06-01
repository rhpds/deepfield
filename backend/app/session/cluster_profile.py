"""Per-cluster adaptive profile — learns baseline behavior and auto-tunes thresholds.

Each cluster gets its own profile that tracks signal patterns, namespace noise,
and dedup/suppression thresholds. Profiles persist to DB and reload on startup.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Optional, Set

logger = logging.getLogger("deepfield.profile")

DEFAULT_DEDUP_WINDOW = 60
DEFAULT_DAMPEN_THRESHOLD = 10
HIGH_VOLUME_DEDUP_WINDOW = 600
MAX_DEDUP_WINDOW = 3600
NOISE_SCORE_ALPHA = 0.1


@dataclass
class ClusterProfile:
    cluster_id: str

    baseline_signals_per_second: float = 0.0
    baseline_signal_types: Dict[str, float] = field(default_factory=dict)
    baseline_namespace_rates: Dict[str, float] = field(default_factory=dict)
    baseline_pod_count: int = 0
    baseline_node_count: int = 0

    dedup_windows: Dict[str, int] = field(default_factory=dict)
    namespace_dampen_thresholds: Dict[str, int] = field(default_factory=dict)
    suppress_types: Set[str] = field(default_factory=set)

    namespace_noise_scores: Dict[str, float] = field(default_factory=dict)

    model_health: Dict[str, Dict] = field(default_factory=dict)

    updated_at: str = ""
    confidence: float = 0.0

    def get_dedup_window(self, signal_type: str) -> int:
        return self.dedup_windows.get(signal_type, DEFAULT_DEDUP_WINDOW)

    def get_dampen_threshold(self, namespace: str) -> int:
        return self.namespace_dampen_thresholds.get(namespace, DEFAULT_DAMPEN_THRESHOLD)

    def is_noise_namespace(self, namespace: str, threshold: float = 0.95) -> bool:
        return self.namespace_noise_scores.get(namespace, 0.0) > threshold

    def should_suppress_type(self, signal_type: str) -> bool:
        return signal_type in self.suppress_types

    def update_from_signals(self, signal_counts: Dict[str, int], namespace_counts: Dict[str, int],
                            total_signals: int, duration_hours: float):
        """Recompute baselines and auto-adjust thresholds from recent signal data."""
        if duration_hours <= 0:
            return

        sps = total_signals / max(duration_hours * 3600, 1)
        self.baseline_signals_per_second = (
            self.baseline_signals_per_second * 0.8 + sps * 0.2
            if self.baseline_signals_per_second > 0 else sps
        )

        for sig_type, count in signal_counts.items():
            rate = count / duration_hours
            old = self.baseline_signal_types.get(sig_type, 0.0)
            self.baseline_signal_types[sig_type] = old * 0.8 + rate * 0.2 if old > 0 else rate

            avg_rate = sum(self.baseline_signal_types.values()) / max(len(self.baseline_signal_types), 1)
            if rate > avg_rate * 10:
                current_window = self.dedup_windows.get(sig_type, DEFAULT_DEDUP_WINDOW)
                new_window = min(current_window * 2, MAX_DEDUP_WINDOW)
                if new_window > current_window:
                    self.dedup_windows[sig_type] = new_window
                    logger.info("Auto-tuned dedup window for %s: %ds → %ds (rate %.0f/hr, avg %.0f/hr)",
                                sig_type, current_window, new_window, rate, avg_rate)

        for ns, count in namespace_counts.items():
            rate = count / duration_hours
            old = self.baseline_namespace_rates.get(ns, 0.0)
            self.baseline_namespace_rates[ns] = old * 0.8 + rate * 0.2 if old > 0 else rate

        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.confidence = min(1.0, self.confidence + 0.01)

    def update_noise_scores(self, namespace_total: Dict[str, int], namespace_suppressed: Dict[str, int]):
        """Update noise scores based on what % of signals from each namespace get suppressed/deduped."""
        for ns, total in namespace_total.items():
            if total < 10:
                continue
            suppressed = namespace_suppressed.get(ns, 0)
            raw_score = suppressed / total
            old = self.namespace_noise_scores.get(ns, 0.0)
            self.namespace_noise_scores[ns] = old * (1 - NOISE_SCORE_ALPHA) + raw_score * NOISE_SCORE_ALPHA

            if self.namespace_noise_scores[ns] > 0.9:
                current_threshold = self.namespace_dampen_thresholds.get(ns, DEFAULT_DAMPEN_THRESHOLD)
                new_threshold = max(3, current_threshold // 2)
                if new_threshold < current_threshold:
                    self.namespace_dampen_thresholds[ns] = new_threshold

    def update_model_health(self, model: str, success: bool, latency_ms: float):
        """Track model error rates and latency for auto-deprioritization."""
        if model not in self.model_health:
            self.model_health[model] = {"calls": 0, "errors": 0, "total_latency": 0.0}
        h = self.model_health[model]
        h["calls"] += 1
        if not success:
            h["errors"] += 1
        h["total_latency"] += latency_ms
        h["error_rate"] = h["errors"] / max(h["calls"], 1)
        h["avg_latency"] = h["total_latency"] / max(h["calls"], 1)

    def to_json(self) -> str:
        d = asdict(self)
        d["suppress_types"] = list(d["suppress_types"])
        return json.dumps(d)

    @classmethod
    def from_json(cls, data: str) -> "ClusterProfile":
        d = json.loads(data)
        d["suppress_types"] = set(d.get("suppress_types", []))
        return cls(**d)


_profiles: Dict[str, ClusterProfile] = {}


def get_profile(cluster_id: str) -> ClusterProfile:
    if cluster_id not in _profiles:
        _profiles[cluster_id] = ClusterProfile(cluster_id=cluster_id)
    return _profiles[cluster_id]


def load_profiles_from_db():
    """Load persisted profiles on startup."""
    import asyncio
    import os
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return
    try:
        import asyncpg

        async def _load():
            conn = await asyncpg.connect(db_url)
            try:
                rows = await conn.fetch("SELECT cluster_id, profile_data FROM cluster_profiles")
                for r in rows:
                    try:
                        _profiles[r["cluster_id"]] = ClusterProfile.from_json(r["profile_data"])
                        logger.info("Loaded profile for cluster %s (confidence=%.2f)",
                                    r["cluster_id"], _profiles[r["cluster_id"]].confidence)
                    except Exception as e:
                        logger.warning("Failed to load profile for %s: %s", r["cluster_id"], e)
            finally:
                await conn.close()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_load())
        loop.close()
    except Exception as e:
        logger.debug("No profiles to load: %s", e)


def persist_profile(profile: ClusterProfile):
    """Save profile to DB."""
    from app.db import enqueue_write
    enqueue_write("cluster_profiles", {
        "cluster_id": profile.cluster_id,
        "profile_data": profile.to_json(),
        "confidence": profile.confidence,
    })
