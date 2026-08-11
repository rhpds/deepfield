"""AAP Cascade Bridge — separate instance for Ansible Automation Platform signals.

Isolated from K8s cascade: own agents, own phi-4 context, own Postgres schema.
Uses the same cascade framework with zero code changes.
"""

import logging
import os
import threading
import time

from app.cascade_bridge import CascadeBridge

log = logging.getLogger(__name__)

# Override phi-4 context for AAP domain
AAP_PHI4_SYSTEM = """You are classifying Ansible Automation Platform (AAP) job signals.

Context: This is an infrastructure automation platform running Ceph monitoring, operations tasks, and sandbox management jobs. Most jobs run on a schedule and succeed routinely.

Classify as exactly one of:
- routine_noise: scheduled job succeeded as expected (Ceph monitors, backups, routine ops)
- known_pattern: recurring failure on a known-flaky job, low priority
- needs_attention: unexpected failure or new error pattern, investigate
- real_incident: production impact, critical infrastructure affected

Answer with one word only."""


class AAPCascadeBridge(CascadeBridge):
    """AAP-specific cascade bridge with isolated state."""

    def __init__(self):
        # Set AAP-specific env before parent init
        os.environ["CASCADE_SCHEMA"] = "cascade_aap"
        super().__init__(audit_dir="/tmp/cascade-aap-audit")

        # Override phi-4 system prompt for AAP domain
        import app.cascade_bridge as bridge_module
        bridge_module.PHI4_SYSTEM = AAP_PHI4_SYSTEM

        log.info("AAP Cascade Bridge initialized (separate from K8s)")


_aap_bridge = None
_aap_collector = None
_aap_thread = None
_aap_running = False


def start_aap_cascade():
    """Start the AAP cascade pipeline in a background thread."""
    global _aap_bridge, _aap_collector, _aap_thread, _aap_running

    if _aap_running:
        return {"status": "already running"}

    try:
        from app.collectors.aap import AAPCollector

        # Create AAP bridge with completely clean state
        _aap_bridge = CascadeBridge.__new__(CascadeBridge)
        _aap_bridge.enabled = True
        from intel_inference_router.cascade import CascadePipeline
        from intel_inference_router.cascade.agents import default_agents
        from intel_inference_router.cascade.corpus_analyzer import CorpusAnalyzer
        from intel_inference_router.cascade.dynamic_agents import RepeatFloodSuppressor, DominantNoiseSuppressor
        from intel_inference_router.cascade.promotion import PromotionEngine, Baseline
        from collections import defaultdict

        _aap_bridge.pipeline = CascadePipeline(default_agents())
        _aap_bridge.promotion = PromotionEngine()
        _aap_bridge.stats = __import__('app.cascade_bridge', fromlist=['BridgeStats']).BridgeStats(
            started_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
        _aap_bridge._repeat_suppressor = RepeatFloodSuppressor(max_repeats=3, window_seconds=300)
        _aap_bridge._noise_suppressor = DominantNoiseSuppressor(window_seconds=300)
        _aap_bridge.pipeline.register(_aap_bridge._repeat_suppressor)
        _aap_bridge.pipeline.register(_aap_bridge._noise_suppressor)
        _aap_bridge._activated_types = set()
        _aap_bridge.corpus_analyzer = CorpusAnalyzer(min_frequency=0.05, min_repeat_count=10, repeat_window_seconds=300, analysis_interval=300)
        _aap_bridge._phi4_buffer = []
        _aap_bridge._phi4_max_buffer = 500
        _aap_bridge._phi4_results = []
        _aap_bridge._phi4_running = False
        _aap_bridge._phi4_noise_counts = defaultdict(int)
        _aap_bridge._agent_metrics = {}
        _aap_bridge._agent_rules = {}
        _aap_bridge._promotion_log = []
        _aap_bridge._last_promotion_time = 0
        _aap_bridge._promotion_interval = 300
        _aap_bridge.baseline = Baseline(normal_ranges={})
        _aap_bridge._observed_ranges = defaultdict(lambda: defaultdict(list))
        _aap_bridge._fn_count = 0
        _aap_bridge._fn_evaluated = 0
        _aap_bridge._fn_types = defaultdict(int)
        _aap_bridge._activated_patterns = {}
        _aap_bridge._activation_timestamps = {}
        _aap_bridge._shadow_sample_rate = float(os.getenv("CASCADE_SHADOW_RATE", "0.05"))
        _aap_bridge._shadow_buffer = []
        _aap_bridge._shadow_running = False
        _aap_bridge._shadow_checks = 0
        _aap_bridge._shadow_demotions = 0
        _aap_bridge._activation_ttl_hours = float(os.getenv("CASCADE_ACTIVATION_TTL_HOURS", "72"))
        _aap_bridge._verdict_watermark = ""
        _aap_bridge._verdict_poll_running = False
        _aap_bridge._human_gate = False
        import logging
        logging.getLogger(__name__).info("AAP cascade: clean instance, zero K8s state")

        _aap_collector = AAPCollector(poll_interval=30)

        skip_replay = os.getenv("AAP_SKIP_REPLAY", "").lower() in ("1", "true", "yes")
        if skip_replay:
            _aap_collector._last_job_id = int(os.getenv("AAP_START_JOB_ID", "0"))
            _aap_collector._last_event_id = int(os.getenv("AAP_START_EVENT_ID", "0"))
            _aap_collector._last_activity_id = int(os.getenv("AAP_START_ACTIVITY_ID", "0"))
            log.info("AAP: skipping replay, polling from job=%d event=%d activity=%d",
                     _aap_collector._last_job_id, _aap_collector._last_event_id, _aap_collector._last_activity_id)

        _aap_running = True

        import app.cascade_bridge as bm
        original_phi4 = bm.PHI4_SYSTEM

        def _run():
            global _aap_running
            bm.PHI4_SYSTEM = AAP_PHI4_SYSTEM

            if not skip_replay:
                log.info("AAP: replaying historical signals...")
                all_signals = _aap_collector.collect_all()
                if all_signals:
                    batch_size = 500
                    for i in range(0, len(all_signals), batch_size):
                        batch = all_signals[i:i + batch_size]
                        _aap_bridge.process(batch, [])
                    log.info("AAP: replayed %d signals, compression=%.1f%%",
                             len(all_signals), _aap_bridge.stats.compression_ratio * 100)

            while _aap_running:
                signals = _aap_collector.collect()
                if signals:
                    _aap_bridge.process(signals, [])
                time.sleep(30)

            bm.PHI4_SYSTEM = original_phi4

        _aap_thread = threading.Thread(target=_run, daemon=True)
        _aap_thread.start()

        return {"status": "started", "historical_jobs": "replaying"}
    except Exception as e:
        return {"error": str(e)}


def stop_aap_cascade():
    global _aap_running
    _aap_running = False
    return {"status": "stopped"}


def get_aap_stats():
    if _aap_bridge and _aap_bridge.enabled:
        return {
            "domain": "aap",
            "stats": _aap_bridge.get_stats(),
            "phi4": _aap_bridge.get_phi4_summary(),
            "phi4_results": _aap_bridge.get_phi4_results(10),
            "promotion_log": _aap_bridge.get_promotion_log(20),
            "discovered_agents": _aap_bridge.get_discovered_agents(),
        }
    return {"status": "not running"}
