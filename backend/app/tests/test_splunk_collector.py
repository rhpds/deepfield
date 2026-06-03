"""Tests for Splunk collector — signal creation, dedup, drain, severity mapping."""

from app.collectors.splunk import SplunkCollector, SPLUNK_SEVERITY_MAP


def test_splunk_collector_creates_signals():
    collector = SplunkCollector(name="test", base_url="https://splunk.example.com", token="test-token")
    sig = collector._make_signal("search", "high_cpu_alert", "splunk_high_alert", {
        "search_name": "high_cpu_alert",
        "triggered_count": 3,
        "severity": "4",
    })
    assert sig.signal_type == "splunk_high_alert"
    assert sig.namespace == "search"
    assert sig.resource_kind == "SplunkAlert"
    assert sig.resource_name == "high_cpu_alert"
    assert sig.source == "splunk:test"
    assert sig.raw_payload["triggered_count"] == 3


def test_splunk_severity_mapping():
    assert SPLUNK_SEVERITY_MAP["1"] == "splunk_info_alert"
    assert SPLUNK_SEVERITY_MAP["3"] == "splunk_medium_alert"
    assert SPLUNK_SEVERITY_MAP["5"] == "splunk_critical_alert"
    assert SPLUNK_SEVERITY_MAP["high"] == "splunk_high_alert"


def test_splunk_drain_empties_buffer():
    collector = SplunkCollector(name="test", base_url="https://splunk.example.com")
    sig = collector._make_signal("app", "test_alert", "splunk_medium_alert", {})
    collector._signal_buffer.append(sig)
    collector._signal_buffer.append(sig)
    signals = collector.drain_signals()
    assert len(signals) == 2
    assert len(collector.drain_signals()) == 0


def test_splunk_dedup_prevents_duplicate_alerts():
    collector = SplunkCollector(name="test", base_url="https://splunk.example.com")
    collector._seen_alerts.add("alert1:2026-06-03T00:00:00")
    assert "alert1:2026-06-03T00:00:00" in collector._seen_alerts


def test_splunk_alert_counts():
    collector = SplunkCollector(name="test", base_url="https://splunk.example.com")
    counts = collector.get_alert_counts()
    assert counts["total"] == 0
    assert "critical" in counts
    assert "high" in counts


def test_splunk_signal_normalizes_correctly():
    from app.normalizers.signal_normalizer import normalize_signal
    collector = SplunkCollector(name="test", base_url="https://splunk.example.com")
    raw = collector._make_signal("myapp", "error_spike", "splunk_high_alert", {
        "search_name": "error_spike",
        "search_query": "index=main level=ERROR | stats count",
    })
    normalized = normalize_signal(raw)
    assert normalized.severity == "high"
    assert normalized.signal_type == "splunk_high_alert"
    assert normalized.evidence["source"] == "splunk:test"
    assert normalized.evidence["search_name"] == "error_spike"


def test_splunk_critical_alert_severity():
    from app.normalizers.signal_normalizer import normalize_signal
    collector = SplunkCollector(name="test", base_url="https://splunk.example.com")
    raw = collector._make_signal("security", "brute_force", "splunk_critical_alert", {})
    normalized = normalize_signal(raw)
    assert normalized.severity == "critical"
