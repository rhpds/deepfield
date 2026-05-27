"""Synthetic fleet profiles defining scale parameters."""

from dataclasses import dataclass


@dataclass
class FleetProfile:
    name: str
    clusters: int
    namespaces_per_cluster: int
    pods_per_namespace: int
    total_events: int
    failure_rate: float = 0.02
    description: str = ""


PROFILES: dict[str, FleetProfile] = {
    "tiny": FleetProfile(
        name="tiny",
        clusters=1,
        namespaces_per_cluster=10,
        pods_per_namespace=10,
        total_events=1_000,
        failure_rate=0.02,
        description="Minimal profile for unit tests and quick validation",
    ),
    "small": FleetProfile(
        name="small",
        clusters=5,
        namespaces_per_cluster=20,
        pods_per_namespace=10,
        total_events=10_000,
        failure_rate=0.02,
        description="Small fleet for integration testing",
    ),
    "medium": FleetProfile(
        name="medium",
        clusters=25,
        namespaces_per_cluster=40,
        pods_per_namespace=20,
        total_events=50_000,
        failure_rate=0.02,
        description="Medium fleet — 25 clusters, 50K signals",
    ),
    "medium_full": FleetProfile(
        name="medium_full",
        clusters=25,
        namespaces_per_cluster=40,
        pods_per_namespace=20,
        total_events=250_000,
        failure_rate=0.02,
        description="Full medium fleet — 25 clusters, 250K signals",
    ),
    "large": FleetProfile(
        name="large",
        clusters=100,
        namespaces_per_cluster=50,
        pods_per_namespace=20,
        total_events=1_000_000,
        failure_rate=0.02,
        description="Large fleet for capacity projection testing",
    ),
    "max_q": FleetProfile(
        name="max_q",
        clusters=100,
        namespaces_per_cluster=50,
        pods_per_namespace=20,
        total_events=1_000_000,
        failure_rate=0.02,
        description="Configurable maximum scale profile",
    ),
}


def get_profile(name: str, **overrides) -> FleetProfile:
    if name not in PROFILES:
        raise ValueError(f"Unknown profile: {name}. Available: {list(PROFILES.keys())}")
    profile = PROFILES[name]
    if overrides:
        fields = {f.name for f in profile.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in overrides.items() if k in fields}
        return FleetProfile(**{**{f: getattr(profile, f) for f in fields}, **kwargs})
    return profile
