"""Kafka event publisher — TDD red/green.

Tests that DeepField signal events publish to Kafka topics.
"""

import pytest
from unittest.mock import patch


class TestKafkaPublisherExists:
    def test_kafka_publish_function_exists(self):
        from app.integrations.kafka_publisher import publish_to_kafka
        assert callable(publish_to_kafka)

    def test_topic_mapping(self):
        from app.integrations.kafka_publisher import get_topic_for_event
        assert get_topic_for_event("signal.escalated") == "deepfield-signals"
        assert get_topic_for_event("inference.completed") == "deepfield-inferences"


class TestGracefulDegradation:
    def test_publish_succeeds_when_no_bootstrap(self):
        from app.integrations.kafka_publisher import publish_to_kafka
        with patch("app.integrations.kafka_publisher.KAFKA_BOOTSTRAP", ""):
            result = publish_to_kafka("deepfield-signals", {"test": True})
            assert result is None or result == {}
