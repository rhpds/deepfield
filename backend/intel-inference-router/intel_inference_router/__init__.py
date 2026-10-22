"""Intel CPU Inference Routing Engine.

Provides benchmark-graded model selection, workload classification, and
strategy routing for Intel Xeon CPU inference deployments.
"""

from .bootstrapper import (
    ClassificationScorecard,
    WorkloadBootstrapper,
    WorkloadFingerprint,
    WorkloadProfile,
)
from .corpora import (
    CORPORA_TO_ENDPOINT,
    LANE_LATENCY_TARGETS,
    LANE_MODELS,
    LANE_RESPONSE_FORMAT,
    TASK_LATENCY_THRESHOLDS,
    TASK_TO_LANE,
    CorporaEntry,
    ModelConfig,
    RoutingCorpora,
    RubricScorecard,
    grade_task_latency,
    load_corpora,
    reload_corpora,
    resolve_lane,
    resolve_lane_model,
    resolve_lane_response_format,
)
from .fleet_manager import FleetManager, FleetPlan, FleetScorecard, ModelAllocation
from .models import RoutingDecision
from .scaler import (
    InferenceScaler,
    ModelBudget,
    ModelFootprint,
    ModelLifecycleManager,
    PressureObserver,
    PressureScorecard,
    PressureSnapshot,
    ScalerState,
    estimate_memory_gb,
)
from .strategy_router import DEFAULT_STRATEGY, InferenceStrategy, StrategyRouter
from .task_mapping import (
    DEEPFIELD_TASK_TO_BENCHMARK_SHAPE,
    resolve_benchmark_task,
)

__all__ = [
    # Corpora
    "RoutingCorpora",
    "CorporaEntry",
    "ModelConfig",
    "RubricScorecard",
    "CORPORA_TO_ENDPOINT",
    "TASK_LATENCY_THRESHOLDS",
    "LANE_RESPONSE_FORMAT",
    "grade_task_latency",
    "load_corpora",
    "reload_corpora",
    "resolve_lane_response_format",
    # Strategy
    "InferenceStrategy",
    "StrategyRouter",
    "DEFAULT_STRATEGY",
    # Bootstrapper
    "WorkloadBootstrapper",
    "WorkloadProfile",
    "WorkloadFingerprint",
    "ClassificationScorecard",
    # Audit
    "RoutingDecision",
    # Task mapping
    "DEEPFIELD_TASK_TO_BENCHMARK_SHAPE",
    "resolve_benchmark_task",
    # Scaler
    "InferenceScaler",
    "ScalerState",
    "PressureSnapshot",
    "PressureScorecard",
    "ModelFootprint",
    "ModelBudget",
    "PressureObserver",
    "estimate_memory_gb",
    "ModelLifecycleManager",
    # Fleet manager
    "FleetManager",
    "FleetPlan",
    "FleetScorecard",
    "ModelAllocation",
]
