"""Tests for remote failure class loading from StarGate."""

import re
from unittest.mock import patch, MagicMock
import json


def test_convert_normalized_classes():
    """Verify StarGate's normalized format converts to DeepField's compiled regex."""
    from app.nanoagents.failure_classifier import _load_remote_classes

    mock_response = {
        "classes": [
            {
                "name": "pods_crashlooping",
                "patterns": ["CrashLoopBackOff", "Back-off restarting"],
                "severity": "high",
                "source": "k8s-events",
                "category": "pod_health",
            },
            {
                "name": "image_pull_backoff",
                "patterns": ["ImagePullBackOff", "ErrImagePull"],
                "severity": "medium",
                "source": "k8s-events",
                "category": "pod_health",
            },
        ],
        "count": 2,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__ = MagicMock(return_value=mock_urlopen)
    mock_urlopen.__exit__ = MagicMock(return_value=False)
    mock_urlopen.read.return_value = json.dumps(mock_response).encode()

    with patch.dict("os.environ", {"DEEPFIELD_STARGATE_URL": "http://stargate:8090"}):
        with patch("urllib.request.urlopen", return_value=mock_urlopen):
            result = _load_remote_classes()

    assert result is not None
    assert "pods_crashlooping" in result
    assert "image_pull_backoff" in result
    assert result["pods_crashlooping"]["severity"] == "high"
    assert isinstance(result["pods_crashlooping"]["regex"], re.Pattern)
    assert result["pods_crashlooping"]["regex"].search("CrashLoopBackOff")
    assert result["pods_crashlooping"]["regex"].search("Back-off restarting")
    assert result["pods_crashlooping"]["category"] == "pod_health"


def test_fallback_without_url():
    """Without DEEPFIELD_STARGATE_URL, returns None (caller uses local YAML)."""
    from app.nanoagents.failure_classifier import _load_remote_classes

    with patch.dict("os.environ", {}, clear=True):
        import os
        os.environ.pop("DEEPFIELD_STARGATE_URL", None)
        result = _load_remote_classes()

    assert result is None


def test_fallback_on_network_error():
    """Network errors return None instead of crashing."""
    from app.nanoagents.failure_classifier import _load_remote_classes

    with patch.dict("os.environ", {"DEEPFIELD_STARGATE_URL": "http://unreachable:9999"}):
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            result = _load_remote_classes()

    assert result is None


def test_empty_patterns_skipped():
    """Classes with no patterns are excluded from the result."""
    from app.nanoagents.failure_classifier import _load_remote_classes

    mock_response = {
        "classes": [
            {"name": "no_pattern", "patterns": [], "severity": "low"},
            {"name": "has_pattern", "patterns": ["SomeError"], "severity": "high"},
        ],
        "count": 2,
    }

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__ = MagicMock(return_value=mock_urlopen)
    mock_urlopen.__exit__ = MagicMock(return_value=False)
    mock_urlopen.read.return_value = json.dumps(mock_response).encode()

    with patch.dict("os.environ", {"DEEPFIELD_STARGATE_URL": "http://stargate:8090"}):
        with patch("urllib.request.urlopen", return_value=mock_urlopen):
            result = _load_remote_classes()

    assert result is not None
    assert "no_pattern" not in result
    assert "has_pattern" in result
