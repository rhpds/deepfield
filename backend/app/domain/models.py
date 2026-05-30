"""DeepField domain models."""

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ClusterRef(BaseModel):
    cluster_id: UUID = Field(default_factory=uuid4)
    display_name: str
    environment: Literal["synthetic", "live"]
    source_type: Literal["synthetic", "openshift", "launchpad", "stargate"]
    api_url: Optional[str] = None
    status: str = "active"
    metadata: dict = Field(default_factory=dict)


class RawSignal(BaseModel):
    signal_id: UUID = Field(default_factory=uuid4)
    cluster_id: UUID
    namespace: str
    resource_kind: str
    resource_name: str
    source: str
    signal_type: str
    raw_payload: dict = Field(default_factory=dict)
    timestamp: datetime


class NormalizedSignal(BaseModel):
    signal_id: UUID
    cluster_id: UUID
    namespace: str
    resource_kind: str
    resource_name: str
    signal_type: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    deterministic: bool = True
    labels: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)
    timestamp: datetime


class FilterDecision(BaseModel):
    decision_id: UUID = Field(default_factory=uuid4)
    signal_id: UUID
    filter_name: str
    outcome: Literal["keep", "drop", "suppress", "dedupe", "enrich", "escalate"]
    reason_code: str
    evidence: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_now)


class CandidateFinding(BaseModel):
    finding_id: UUID = Field(default_factory=uuid4)
    clusters: list[UUID]
    namespaces: list[str]
    signal_ids: list[UUID]
    finding_type: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    correlation_keys: dict = Field(default_factory=dict)
    summary: str
    evidence: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class ReasoningTask(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    task_type: Literal[
        "summarize_finding",
        "root_cause_analysis",
        "cross_cluster_correlation",
        "fleet_summary",
        "capacity_estimate",
        "classify_signal",
        "correlate_findings",
        "suggest_remediation",
        "explain_signal",
        "filter_noise",
    ]
    model_preference: Literal[
        "phi4", "qwen3", "qwen3b", "deepseek", "llama70b",
        "granite_2b_cpu", "phi3_mini_cpu", "qwen25_3b_cpu",
        "auto",
    ] = "auto"
    route: Optional[str] = None
    prompt: str
    context: dict = Field(default_factory=dict)
    status: str = "pending"
    metrics: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None


class InferenceResult(BaseModel):
    result_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    model_name: str
    hardware_lane: str
    status: str
    output: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=_now)


class FinalInsight(BaseModel):
    insight_id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    task_ids: list[UUID]
    title: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    summary: str
    affected_clusters: list[UUID]
    affected_namespaces: list[str]
    evidence: dict = Field(default_factory=dict)
    model_results: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class DeepFieldRun(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    mode: Literal["synthetic", "live", "benchmark"]
    profile: str
    started_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None
    status: str = "running"
    config: dict = Field(default_factory=dict)
    metrics_summary: dict = Field(default_factory=dict)
    report_refs: dict = Field(default_factory=dict)


class CapacityProjection(BaseModel):
    run_id: UUID
    clusters_monitored: int
    raw_signals_per_second: float
    reasoning_tasks_per_second: float
    reasoning_compression_ratio: float
    p95_latency_ms: float
    cpu_usage: float
    memory_usage: float
    hpu_usage: Optional[float] = None
    projected_clusters_supported: int
    assumptions: dict = Field(default_factory=dict)


class BenchmarkRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    benchmark_run_id: UUID
    workload_profile: str
    task_type: str
    prompt: str
    input_tokens_estimate: int
    expected_output_tokens: int
    model_preference: str = "auto"
    created_at: datetime = Field(default_factory=_now)
    metadata: dict = Field(default_factory=dict)


class BenchmarkRun(BaseModel):
    benchmark_run_id: UUID = Field(default_factory=uuid4)
    profile: str
    model_profiles: list[str]
    concurrency_levels: list[int]
    request_count: int
    duration_seconds: Optional[float] = None
    status: str = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metrics_summary: dict = Field(default_factory=dict)
    report_refs: dict = Field(default_factory=dict)


class BenchmarkResult(BaseModel):
    result_id: UUID = Field(default_factory=uuid4)
    benchmark_run_id: UUID
    request_id: UUID
    model_name: str
    hardware_lane: str
    concurrency_level: int
    status: str
    latency_ms: float
    ttft_ms: Optional[float] = None
    tokens_in: int
    tokens_out: int
    tokens_per_second: float
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=_now)
