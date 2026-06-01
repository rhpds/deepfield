"""Tests for the adaptive cluster profile system."""

import json
import pytest

from app.session.cluster_profile import ClusterProfile, get_profile


class TestClusterProfileBasics:
    def test_default_profile_values(self):
        p = ClusterProfile(cluster_id="test")
        assert p.cluster_id == "test"
        assert p.confidence == 0.0
        assert p.baseline_signals_per_second == 0.0
        assert len(p.dedup_windows) == 0
        assert len(p.namespace_noise_scores) == 0

    def test_get_dedup_window_default(self):
        p = ClusterProfile(cluster_id="test")
        assert p.get_dedup_window("pod_crashloop") == 60

    def test_get_dedup_window_custom(self):
        p = ClusterProfile(cluster_id="test", dedup_windows={"event_failedscheduling": 600})
        assert p.get_dedup_window("event_failedscheduling") == 600
        assert p.get_dedup_window("pod_crashloop") == 60

    def test_get_dampen_threshold_default(self):
        p = ClusterProfile(cluster_id="test")
        assert p.get_dampen_threshold("kube-system") == 10

    def test_get_dampen_threshold_custom(self):
        p = ClusterProfile(cluster_id="test", namespace_dampen_thresholds={"noisy-ns": 3})
        assert p.get_dampen_threshold("noisy-ns") == 3
        assert p.get_dampen_threshold("quiet-ns") == 10

    def test_noise_namespace_detection(self):
        p = ClusterProfile(cluster_id="test", namespace_noise_scores={"noisy": 0.97, "clean": 0.2})
        assert p.is_noise_namespace("noisy")
        assert not p.is_noise_namespace("clean")
        assert not p.is_noise_namespace("unknown")

    def test_suppress_type(self):
        p = ClusterProfile(cluster_id="test", suppress_types={"event_pulling"})
        assert p.should_suppress_type("event_pulling")
        assert not p.should_suppress_type("pod_crashloop")


class TestClusterProfileLearning:
    def test_update_from_signals_sets_baseline(self):
        p = ClusterProfile(cluster_id="test")
        p.update_from_signals(
            signal_counts={"pod_crashloop": 100, "event_failedscheduling": 5000},
            namespace_counts={"ns-a": 200, "ns-b": 4900},
            total_signals=5100,
            duration_hours=1.0,
        )
        assert p.baseline_signals_per_second > 0
        assert "pod_crashloop" in p.baseline_signal_types
        assert "event_failedscheduling" in p.baseline_signal_types
        assert p.confidence > 0

    def test_high_volume_type_auto_widens_dedup(self):
        p = ClusterProfile(cluster_id="test")
        p.update_from_signals(
            signal_counts={"type_a": 10, "type_b": 10, "type_c": 10, "type_d": 10,
                           "event_failedscheduling": 50000},
            namespace_counts={},
            total_signals=50040,
            duration_hours=1.0,
        )
        assert p.get_dedup_window("event_failedscheduling") > 60

    def test_update_noise_scores(self):
        p = ClusterProfile(cluster_id="test")
        for _ in range(20):
            p.update_noise_scores(
                namespace_total={"noisy-ns": 1000, "clean-ns": 100},
                namespace_suppressed={"noisy-ns": 950, "clean-ns": 5},
            )
        assert p.namespace_noise_scores["noisy-ns"] > 0.8
        assert p.namespace_noise_scores["clean-ns"] < 0.15

    def test_high_noise_auto_tightens_dampening(self):
        p = ClusterProfile(cluster_id="test")
        p.namespace_noise_scores["noisy-ns"] = 0.95
        p.namespace_dampen_thresholds["noisy-ns"] = 10
        p.update_noise_scores(
            namespace_total={"noisy-ns": 1000},
            namespace_suppressed={"noisy-ns": 950},
        )
        assert p.get_dampen_threshold("noisy-ns") < 10

    def test_model_health_tracking(self):
        p = ClusterProfile(cluster_id="test")
        for _ in range(80):
            p.update_model_health("good_model", success=True, latency_ms=200)
        for _ in range(20):
            p.update_model_health("good_model", success=False, latency_ms=5000)
        assert p.model_health["good_model"]["calls"] == 100
        assert p.model_health["good_model"]["error_rate"] == pytest.approx(0.2, abs=0.01)

    def test_confidence_increases(self):
        p = ClusterProfile(cluster_id="test")
        assert p.confidence == 0.0
        for _ in range(5):
            p.update_from_signals({"a": 10}, {}, 10, 1.0)
        assert p.confidence > 0.0


class TestClusterProfileSerialization:
    def test_json_roundtrip(self):
        p = ClusterProfile(
            cluster_id="test",
            dedup_windows={"event_failedscheduling": 600},
            suppress_types={"event_pulling"},
            namespace_noise_scores={"noisy": 0.95},
            confidence=0.5,
        )
        j = p.to_json()
        p2 = ClusterProfile.from_json(j)
        assert p2.cluster_id == "test"
        assert p2.get_dedup_window("event_failedscheduling") == 600
        assert p2.should_suppress_type("event_pulling")
        assert p2.namespace_noise_scores["noisy"] == 0.95
        assert p2.confidence == 0.5

    def test_suppress_types_serializes_as_list(self):
        p = ClusterProfile(cluster_id="test", suppress_types={"a", "b"})
        j = json.loads(p.to_json())
        assert isinstance(j["suppress_types"], list)
        assert set(j["suppress_types"]) == {"a", "b"}


class TestGetProfile:
    def test_returns_new_profile_for_unknown_cluster(self):
        p = get_profile("brand-new-cluster-xyz")
        assert p.cluster_id == "brand-new-cluster-xyz"
        assert p.confidence == 0.0

    def test_returns_same_instance(self):
        p1 = get_profile("singleton-test")
        p2 = get_profile("singleton-test")
        assert p1 is p2
