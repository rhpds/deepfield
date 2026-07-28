"""RED/GREEN TDD: tests written FIRST.

Tests for StarGate<->Deepfield integration:
- Signal conversion preserves cluster identity
- Namespace field read correctly
- lab_code and failure_class extracted
- Outbound push to StarGate
"""

from unittest.mock import patch
from uuid import UUID

from app.api.integration import IntegrationEvent, _convert_stargate_event
from app.integrations.event_publisher import push_incident_to_stargate


# ---------- helpers ----------

def _stargate_event(**overrides) -> IntegrationEvent:
    payload = {
        "cluster": "ocpv05",
        "namespace": "sandbox-abc",
        "run_id": "run-42",
        "stage_id": "stage-7",
        "lab_code": "LAB-009",
        "outcome": "FAIL",
        "failure_class": "timeout",
        "message": "stage timed out after 300s",
        "priority": "high",
        "systemic": True,
    }
    payload.update(overrides.pop("payload", {}))
    defaults = {
        "source": "stargate",
        "event_type": "stage_result",
        "event_id": "evt-001",
        "timestamp": "2026-07-27T12:00:00Z",
        "payload": payload,
    }
    defaults.update(overrides)
    return IntegrationEvent(**defaults)


# ---------- A. Signal conversion tests ----------

def test_stargate_event_preserves_cluster_id():
    """Two events from the same cluster must get the same cluster_id (uuid5, not uuid4)."""
    evt_a = _stargate_event(event_id="evt-a")
    evt_b = _stargate_event(event_id="evt-b")
    sig_a = _convert_stargate_event(evt_a)
    sig_b = _convert_stargate_event(evt_b)
    assert sig_a.cluster_id == sig_b.cluster_id
    assert isinstance(sig_a.cluster_id, UUID)


def test_stargate_event_reads_namespace_field():
    """Payload with namespace='sandbox-abc' -> signal.namespace == 'sandbox-abc'."""
    sig = _convert_stargate_event(_stargate_event())
    assert sig.namespace == "sandbox-abc"


def test_stargate_event_namespace_fallback_to_cluster():
    """Payload without namespace but with cluster='ocpv05' -> signal.namespace == 'ocpv05'."""
    evt = IntegrationEvent(
        source="stargate",
        event_type="stage_result",
        event_id="evt-fallback",
        timestamp="2026-07-27T12:00:00Z",
        payload={"cluster": "ocpv05", "outcome": "PASS"},
    )
    sig = _convert_stargate_event(evt)
    assert sig.namespace == "ocpv05"


def test_stargate_event_extracts_failure_class():
    """failure_class in payload is accessible in raw_payload."""
    sig = _convert_stargate_event(_stargate_event())
    assert sig.raw_payload.get("failure_class") == "timeout"


def test_stargate_event_extracts_lab_code():
    """lab_code in payload -> resource_name includes it."""
    sig = _convert_stargate_event(_stargate_event())
    assert sig.resource_name == "LAB-009"


def test_stargate_event_extracts_message():
    """message in payload is stored in raw_payload."""
    sig = _convert_stargate_event(_stargate_event())
    assert sig.raw_payload.get("message") == "stage timed out after 300s"


def test_stargate_event_extracts_priority():
    """priority in payload is stored in raw_payload."""
    sig = _convert_stargate_event(_stargate_event())
    assert sig.raw_payload.get("priority") == "high"


def test_stargate_event_extracts_systemic():
    """systemic in payload is stored in raw_payload."""
    sig = _convert_stargate_event(_stargate_event())
    assert sig.raw_payload.get("systemic") is True


# ---------- B. Outbound publisher tests ----------

def test_push_incident_to_stargate_exists():
    """Function exists in event_publisher."""
    assert callable(push_incident_to_stargate)


def test_push_incident_payload_shape():
    """Validate the payload has expected keys."""
    incident = {
        "incident_id": "inc-001",
        "namespace": "sandbox-abc",
        "cluster": "ocpv05",
        "failure_class": "timeout",
        "severity": "high",
        "confidence": 0.9,
        "rca_output": "Root-cause: scheduler pressure",
        "correlated_signals": ["sig-1", "sig-2"],
        "remediation_options": ["scale-up"],
        "evidence_chain": ["evt-a"],
        "lab_code": "LAB-009",
        "signal_count": 5,
    }
    with patch("app.integrations.event_publisher.STARGATE_API_URL", "http://fake:8080"), \
         patch("app.integrations.event_publisher.httpx") as mock_httpx:
        mock_resp = mock_httpx.post.return_value
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        result = push_incident_to_stargate(incident)

        assert result is True
        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        for key in ("incident_id", "namespace", "cluster", "failure_class",
                     "severity", "confidence", "rca_output",
                     "correlated_signals", "remediation_options", "evidence_chain"):
            assert key in payload, f"Missing key: {key}"


def test_push_disabled_without_url():
    """When STARGATE_API_URL not set, function is a no-op."""
    with patch("app.integrations.event_publisher.STARGATE_API_URL", ""):
        result = push_incident_to_stargate({"incident_id": "x"})
        assert result is False


def test_push_failure_doesnt_crash():
    """Network errors caught and logged, not raised."""
    with patch("app.integrations.event_publisher.STARGATE_API_URL", "http://fake:8080"), \
         patch("app.integrations.event_publisher.httpx") as mock_httpx:
        mock_httpx.post.side_effect = ConnectionError("network down")
        result = push_incident_to_stargate({"incident_id": "x"})
        assert result is False


def test_push_includes_source_deepfield():
    """payload.source == 'deepfield'."""
    with patch("app.integrations.event_publisher.STARGATE_API_URL", "http://fake:8080"), \
         patch("app.integrations.event_publisher.httpx") as mock_httpx:
        mock_resp = mock_httpx.post.return_value
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        push_incident_to_stargate({"incident_id": "x"})

        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["source"] == "deepfield"
