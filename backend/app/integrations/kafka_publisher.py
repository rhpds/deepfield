"""Kafka event publisher for DeepField signal and inference events."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("deepfield.kafka")

KAFKA_BOOTSTRAP = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "ecosystem-kafka-kafka-bootstrap.ecosystem-kafka.svc:9092",
)

TOPIC_MAP = {
    "signal.escalated": "deepfield-signals",
    "signal.dropped": "deepfield-signals",
    "finding.correlated": "deepfield-signals",
    "inference.completed": "deepfield-inferences",
    "inference.failed": "deepfield-inferences",
    "session.started": "deepfield-signals",
    "session.stopped": "deepfield-signals",
}

AUDIT_TOPIC = "audit-trail"

_producer = None


def _get_producer():
    global _producer
    if _producer is not None:
        return _producer
    if not KAFKA_BOOTSTRAP:
        return None
    try:
        from kafka import KafkaProducer
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks=1, retries=2, request_timeout_ms=5000, max_block_ms=3000,
        )
        logger.info("Kafka producer connected to %s", KAFKA_BOOTSTRAP)
        return _producer
    except ImportError:
        logger.debug("kafka-python not installed — Kafka publishing disabled")
        return None
    except Exception as e:
        logger.debug("Kafka producer init failed: %s", e)
        return None


def get_topic_for_event(event_type: str) -> str:
    return TOPIC_MAP.get(event_type, "deepfield-signals")


def get_audit_topic() -> str:
    return AUDIT_TOPIC


def publish_to_kafka(topic: str, payload: dict, key: str = None) -> Optional[dict]:
    if not KAFKA_BOOTSTRAP:
        return {}
    producer = _get_producer()
    if not producer:
        return {}
    try:
        producer.send(topic, value=payload, key=key)
        producer.flush(timeout=3)
        return {"published": True, "topic": topic}
    except Exception as e:
        logger.debug("Kafka publish to %s failed: %s", topic, e)
        return {}


PIPELINE_TOPICS = {
    "raw": "deepfield-raw-signals",
    "filtered": "deepfield-filtered-signals",
    "findings": "deepfield-findings",
    "incidents": "deepfield-incidents",
    "tarsy_requested": "tarsy-investigation-requested",
}


def publish_raw_signal(signal_dict: dict) -> None:
    """Publish a raw signal to the pipeline topic. Key by namespace for partition ordering."""
    ns = signal_dict.get("namespace", "unknown")
    publish_to_kafka(PIPELINE_TOPICS["raw"], signal_dict, key=ns)


def publish_raw_signal_async(signal_dict: dict) -> None:
    """Fire-and-forget publish — never blocks the caller. Drops silently on failure."""
    if not KAFKA_BOOTSTRAP:
        return
    producer = _get_producer()
    if not producer:
        return
    try:
        ns = signal_dict.get("namespace", "unknown")
        producer.send(PIPELINE_TOPICS["raw"], value=signal_dict, key=ns)
    except Exception:
        pass


def publish_filtered_signal(signal_dict: dict) -> None:
    """Publish a kept/escalated signal after nano-agent processing."""
    ns = signal_dict.get("namespace", "unknown")
    publish_to_kafka(PIPELINE_TOPICS["filtered"], signal_dict, key=ns)


def publish_finding(finding_dict: dict) -> None:
    """Publish a correlated finding."""
    ns = finding_dict.get("namespaces", ["unknown"])[0] if finding_dict.get("namespaces") else "unknown"
    publish_to_kafka(PIPELINE_TOPICS["findings"], finding_dict, key=ns)


def publish_incident_event(incident_dict: dict) -> None:
    """Publish incident state change."""
    publish_to_kafka(PIPELINE_TOPICS["incidents"], incident_dict, key=incident_dict.get("id", ""))


def publish_tarsy_request(request_dict: dict) -> None:
    """Publish a TARSy investigation request. Key by originator_id for partition ordering."""
    publish_to_kafka(
        PIPELINE_TOPICS["tarsy_requested"],
        request_dict,
        key=request_dict.get("originator_id", ""),
    )


def publish_event(event_type: str, payload: dict) -> None:
    payload["_kafka_topic"] = get_topic_for_event(event_type)
    payload["_published_at"] = datetime.now(timezone.utc).isoformat()
    publish_to_kafka(payload["_kafka_topic"], payload, key=payload.get("session_id"))
    publish_to_kafka(AUDIT_TOPIC, payload, key=payload.get("session_id"))
