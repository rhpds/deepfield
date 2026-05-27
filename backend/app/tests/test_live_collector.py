"""Tests for live collector — read-only interface."""

from app.collectors.openshift import OpenShiftCollector


def test_live_collector_is_read_only():
    collector = OpenShiftCollector(cluster_name="test", api_url="https://fake.cluster:6443")
    assert collector.read_only is True


def test_live_collector_returns_signals_structure():
    collector = OpenShiftCollector(
        cluster_name="test", api_url="https://fake.cluster:6443", token="fake"
    )
    # Without a real cluster, collect will return empty due to oc failures
    clusters, signals = collector.collect()
    assert isinstance(clusters, list)
    assert isinstance(signals, list)
    assert len(clusters) == 1
    assert clusters[0].display_name == "test"
    assert clusters[0].environment == "live"


def test_namespace_filtering():
    collector = OpenShiftCollector(
        cluster_name="test", api_url="https://fake:6443",
        include_namespaces=["stargate*", "launchpad*"],
        exclude_namespaces=["openshift-*"],
    )
    assert collector._ns_allowed("stargate") is True
    assert collector._ns_allowed("stargate-test") is True
    assert collector._ns_allowed("launchpad-sandbox-abc") is True
    assert collector._ns_allowed("openshift-monitoring") is False
    assert collector._ns_allowed("kube-system") is False  # not in include patterns
    assert collector._ns_allowed("random-ns") is False   # not in include patterns
