"""Signal types and failure scenarios for synthetic fleet generation."""

from dataclasses import dataclass, field

SIGNAL_TYPES = [
    "pod_running",
    "pod_pending",
    "pod_crashloop",
    "pod_imagepullbackoff",
    "route_ready",
    "route_unhealthy",
    "pvc_bound",
    "pvc_pending",
    "node_ready",
    "node_pressure",
    "namespace_quota_ok",
    "namespace_quota_exceeded",
    "vm_running",
    "vm_failed",
    "kserve_ready",
    "kserve_not_ready",
    "kafka_lag_normal",
    "kafka_lag_high",
    "launchpad_lab_active",
    "launchpad_lab_failed",
    "launchpad_lab_expired",
    "stargate_stage_passed",
    "stargate_stage_failed",
    "stargate_run_completed",
]

HEALTHY_SIGNALS = [
    "pod_running",
    "route_ready",
    "pvc_bound",
    "node_ready",
    "namespace_quota_ok",
    "vm_running",
    "kserve_ready",
    "kafka_lag_normal",
    "launchpad_lab_active",
    "stargate_stage_passed",
    "stargate_run_completed",
]

WARNING_SIGNALS = [
    "pod_pending",
    "pvc_pending",
    "namespace_quota_exceeded",
    "kafka_lag_high",
    "launchpad_lab_expired",
]

FAILURE_SIGNALS = [
    "pod_crashloop",
    "pod_imagepullbackoff",
    "route_unhealthy",
    "node_pressure",
    "vm_failed",
    "kserve_not_ready",
    "launchpad_lab_failed",
    "stargate_stage_failed",
]

SIGNAL_WEIGHTS = {
    "pod_running": 30.0,
    "route_ready": 10.0,
    "pvc_bound": 5.0,
    "node_ready": 8.0,
    "namespace_quota_ok": 5.0,
    "vm_running": 3.0,
    "kserve_ready": 4.0,
    "kafka_lag_normal": 3.0,
    "launchpad_lab_active": 2.0,
    "pod_pending": 6.0,
    "pvc_pending": 3.0,
    "namespace_quota_exceeded": 2.0,
    "kafka_lag_high": 2.0,
    "launchpad_lab_expired": 1.0,
    "pod_crashloop": 4.0,
    "pod_imagepullbackoff": 3.0,
    "route_unhealthy": 2.0,
    "node_pressure": 2.0,
    "vm_failed": 1.0,
    "kserve_not_ready": 2.0,
    "launchpad_lab_failed": 1.0,
    "stargate_stage_passed": 1.0,
    "stargate_stage_failed": 2.0,
    "stargate_run_completed": 1.0,
}

SIGNAL_RESOURCE_KIND = {
    "pod_running": "Pod",
    "pod_pending": "Pod",
    "pod_crashloop": "Pod",
    "pod_imagepullbackoff": "Pod",
    "route_ready": "Route",
    "route_unhealthy": "Route",
    "pvc_bound": "PersistentVolumeClaim",
    "pvc_pending": "PersistentVolumeClaim",
    "node_ready": "Node",
    "node_pressure": "Node",
    "namespace_quota_ok": "ResourceQuota",
    "namespace_quota_exceeded": "ResourceQuota",
    "vm_running": "VirtualMachine",
    "vm_failed": "VirtualMachine",
    "kserve_ready": "InferenceService",
    "kserve_not_ready": "InferenceService",
    "kafka_lag_normal": "KafkaTopic",
    "kafka_lag_high": "KafkaTopic",
    "launchpad_lab_active": "LaunchpadSession",
    "launchpad_lab_failed": "LaunchpadSession",
    "launchpad_lab_expired": "LaunchpadSession",
    "stargate_stage_passed": "StarGateRun",
    "stargate_stage_failed": "StarGateRun",
    "stargate_run_completed": "StarGateRun",
}


@dataclass
class FailureScenario:
    name: str
    description: str
    affected_signal_types: list[str]
    severity: str
    probability: float


FAILURE_SCENARIOS = [
    FailureScenario(
        name="single_namespace_failure",
        description="Multiple pods crash in a single namespace",
        affected_signal_types=["pod_crashloop", "pod_imagepullbackoff"],
        severity="high",
        probability=0.25,
    ),
    FailureScenario(
        name="route_no_endpoints",
        description="Route has no healthy backend endpoints",
        affected_signal_types=["route_unhealthy", "pod_crashloop"],
        severity="high",
        probability=0.15,
    ),
    FailureScenario(
        name="pvc_storage_delay",
        description="PVC stuck in pending state waiting for storage provisioner",
        affected_signal_types=["pvc_pending", "pod_pending"],
        severity="medium",
        probability=0.10,
    ),
    FailureScenario(
        name="node_pressure_cascade",
        description="Node under memory/CPU pressure causing pod evictions",
        affected_signal_types=["node_pressure", "pod_pending", "pod_crashloop"],
        severity="critical",
        probability=0.08,
    ),
    FailureScenario(
        name="model_endpoint_slow",
        description="KServe model endpoint degraded or not ready",
        affected_signal_types=["kserve_not_ready"],
        severity="high",
        probability=0.10,
    ),
    FailureScenario(
        name="kafka_backpressure",
        description="Kafka consumer lag exceeds threshold",
        affected_signal_types=["kafka_lag_high"],
        severity="medium",
        probability=0.10,
    ),
    FailureScenario(
        name="quota_exceeded",
        description="Namespace resource quota exceeded blocking new pods",
        affected_signal_types=["namespace_quota_exceeded", "pod_pending"],
        severity="medium",
        probability=0.10,
    ),
    FailureScenario(
        name="cross_cluster_model_latency",
        description="Model endpoints degraded across multiple clusters",
        affected_signal_types=["kserve_not_ready", "kafka_lag_high"],
        severity="critical",
        probability=0.05,
    ),
    FailureScenario(
        name="launchpad_lab_validation_failure",
        description="Launchpad lab session failed validation checks",
        affected_signal_types=["launchpad_lab_failed"],
        severity="medium",
        probability=0.07,
    ),
]
