"""Correlation key extractors for grouping related signals."""

from app.domain.models import NormalizedSignal


def namespace_key(s: NormalizedSignal) -> str:
    return f"ns:{s.cluster_id}:{s.namespace}"


def resource_key(s: NormalizedSignal) -> str:
    return f"res:{s.cluster_id}:{s.namespace}:{s.resource_kind}:{s.resource_name}"


def cluster_key(s: NormalizedSignal) -> str:
    return f"cluster:{s.cluster_id}"


def signal_type_key(s: NormalizedSignal) -> str:
    return f"type:{s.signal_type}"


def cross_cluster_type_key(s: NormalizedSignal) -> str:
    return f"xcluster:{s.signal_type}"
