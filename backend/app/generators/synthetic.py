"""Deterministic synthetic fleet signal generator."""

import random
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5, NAMESPACE_DNS

from app.domain.models import ClusterRef, RawSignal
from app.generators.profiles import FleetProfile, get_profile
from app.generators.signal_types import (
    FAILURE_SCENARIOS,
    FAILURE_SIGNALS,
    HEALTHY_SIGNALS,
    SIGNAL_RESOURCE_KIND,
    SIGNAL_WEIGHTS,
    WARNING_SIGNALS,
)

_NS = NAMESPACE_DNS

APP_NAMES = [
    "frontend", "backend", "api-gateway", "auth-service", "user-service",
    "order-service", "payment-service", "inventory-service", "notification-service",
    "analytics-service", "search-service", "cache-service", "worker", "scheduler",
    "monitoring", "logging", "ingestion", "transformer", "exporter", "operator",
]

NAMESPACE_PURPOSES = [
    "prod", "staging", "dev", "cicd", "monitoring", "logging",
    "data", "ml", "infra", "platform", "app", "service",
]


class SyntheticFleetGenerator:
    def __init__(self, profile: str, seed: int = 42, **overrides):
        self.profile: FleetProfile = get_profile(profile, **overrides)
        self.seed = seed
        self.rng = random.Random(seed)

    def _deterministic_uuid(self, *parts: str) -> UUID:
        key = ":".join(str(p) for p in parts)
        return uuid5(_NS, f"deepfield:{self.seed}:{key}")

    def generate_clusters(self) -> list[ClusterRef]:
        clusters = []
        for i in range(self.profile.clusters):
            cid = self._deterministic_uuid("cluster", i)
            clusters.append(
                ClusterRef(
                    cluster_id=cid,
                    display_name=f"cluster-{i:03d}",
                    environment="synthetic",
                    source_type="synthetic",
                )
            )
        return clusters

    def _generate_namespaces(self, cluster_idx: int) -> list[str]:
        namespaces = []
        for j in range(self.profile.namespaces_per_cluster):
            purpose = self.rng.choice(NAMESPACE_PURPOSES)
            namespaces.append(f"ns-{purpose}-{j:04d}")
        return namespaces

    def _generate_resource_name(self, signal_type: str, ns: str, idx: int) -> str:
        kind = SIGNAL_RESOURCE_KIND.get(signal_type, "Unknown")
        app = self.rng.choice(APP_NAMES)
        suffix = f"{self.rng.randint(1000, 9999):04x}"
        if kind == "Pod":
            return f"{app}-{suffix}-{self.rng.choice('abcdefghijklmnop')}{self.rng.choice('abcdefghijklmnop')}{self.rng.choice('0123456789')}{self.rng.choice('abcdefghijklmnop')}{self.rng.choice('0123456789')}"
        elif kind == "Node":
            return f"worker-{self.rng.randint(1, 20):02d}"
        elif kind == "Route":
            return f"{app}-route"
        elif kind == "PersistentVolumeClaim":
            return f"{app}-data-{self.rng.randint(0, 9)}"
        elif kind == "VirtualMachine":
            return f"vm-{app}-{suffix}"
        elif kind == "InferenceService":
            return f"model-{app}-{suffix}"
        elif kind == "KafkaTopic":
            return f"{app}-events"
        elif kind == "LaunchpadSession":
            return f"lab-{suffix}"
        else:
            return f"{app}-{suffix}"

    def _pick_signal_type(self, force_failure: bool = False) -> str:
        if force_failure:
            return self.rng.choice(FAILURE_SIGNALS)
        # 95% healthy, 5% warnings (medium-severity → routes to Xeon CPU for cheap reasoning)
        # Hard failures only from force_failure (controlled by failure_rate param)
        if self.rng.random() < 0.05:
            return self.rng.choice(WARNING_SIGNALS)
        return self.rng.choices(HEALTHY_SIGNALS, k=1)[0]

    def _build_payload(self, signal_type: str) -> dict:
        if signal_type == "pod_crashloop":
            return {"restartCount": self.rng.randint(3, 50), "reason": "CrashLoopBackOff"}
        elif signal_type == "pod_imagepullbackoff":
            return {"reason": "ImagePullBackOff", "image": f"registry.example.com/app:{self.rng.randint(1, 99)}"}
        elif signal_type == "node_pressure":
            pressure = self.rng.choice(["MemoryPressure", "DiskPressure", "PIDPressure"])
            return {"condition": pressure, "status": "True"}
        elif signal_type == "kafka_lag_high":
            return {"consumerGroup": f"group-{self.rng.randint(1, 10)}", "lag": self.rng.randint(10000, 500000)}
        elif signal_type == "namespace_quota_exceeded":
            return {"resource": self.rng.choice(["cpu", "memory", "pods"]), "used": "100%"}
        elif signal_type == "kserve_not_ready":
            return {"reason": "RevisionFailed", "model": f"model-{self.rng.randint(1, 5)}"}
        elif signal_type == "launchpad_lab_failed":
            return {"labId": f"lab-{self.rng.randint(100, 999)}", "reason": "ValidationError"}
        return {}

    def generate_signals(self, clusters: list[ClusterRef]) -> list[RawSignal]:
        signals: list[RawSignal] = []
        base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        time_window_seconds = 3600

        failure_count = int(self.profile.total_events * self.profile.failure_rate)
        failure_indices = set(self.rng.sample(range(self.profile.total_events), min(failure_count, self.profile.total_events)))

        for i in range(self.profile.total_events):
            cluster = self.rng.choice(clusters)
            cluster_idx = next(j for j, c in enumerate(clusters) if c.cluster_id == cluster.cluster_id)
            namespaces = self._generate_namespaces(cluster_idx)
            ns = self.rng.choice(namespaces)

            force_failure = i in failure_indices
            signal_type = self._pick_signal_type(force_failure=force_failure)
            resource_kind = SIGNAL_RESOURCE_KIND.get(signal_type, "Unknown")
            resource_name = self._generate_resource_name(signal_type, ns, i)
            ts_offset = self.rng.uniform(0, time_window_seconds)
            timestamp = base_time + timedelta(seconds=ts_offset)

            sig_id = self._deterministic_uuid("signal", i)
            signals.append(
                RawSignal(
                    signal_id=sig_id,
                    cluster_id=cluster.cluster_id,
                    namespace=ns,
                    resource_kind=resource_kind,
                    resource_name=resource_name,
                    source="synthetic",
                    signal_type=signal_type,
                    raw_payload=self._build_payload(signal_type),
                    timestamp=timestamp,
                )
            )

        return signals

    def generate(self) -> tuple[list[ClusterRef], list[RawSignal]]:
        clusters = self.generate_clusters()
        signals = self.generate_signals(clusters)
        return clusters, signals
