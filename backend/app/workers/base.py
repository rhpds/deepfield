"""Base Kafka consumer worker with offset management and graceful shutdown."""

import json
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("deepfield.workers")

_KAFKA_BOOTSTRAP = None


def _get_bootstrap():
    global _KAFKA_BOOTSTRAP
    if _KAFKA_BOOTSTRAP is None:
        import os
        _KAFKA_BOOTSTRAP = os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS",
            "ecosystem-kafka-kafka-bootstrap.ecosystem-kafka.svc:9092",
        )
    return _KAFKA_BOOTSTRAP


class KafkaWorker:
    """Base class for Kafka consumer workers.

    Handles consumer lifecycle, deserialization, and graceful shutdown.
    Subclasses implement ``process(message_dict)`` for business logic.
    """

    topic: str = ""
    group_id: str = "deepfield-workers"
    auto_offset_reset: str = "latest"

    def __init__(self):
        self._consumer = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._messages_processed = 0
        self._errors = 0
        self._started_at: Optional[float] = None

    def _create_consumer(self, group_id_override: str = None):
        from kafka import KafkaConsumer
        return KafkaConsumer(
            self.topic,
            bootstrap_servers=_get_bootstrap(),
            group_id=group_id_override or self.group_id,
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=True,
            auto_commit_interval_ms=5000,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            consumer_timeout_ms=1000,
            max_poll_interval_ms=300000,
            session_timeout_ms=30000,
        )

    def seek_to_beginning(self):
        if self._consumer:
            self._consumer.poll(timeout_ms=0)
            self._consumer.seek_to_beginning()

    def seek_to_timestamp(self, timestamp_ms: int):
        if self._consumer:
            self._consumer.poll(timeout_ms=0)
            partitions = self._consumer.assignment()
            offsets = self._consumer.offsets_for_times(
                {tp: timestamp_ms for tp in partitions}
            )
            for tp, offset_and_ts in (offsets or {}).items():
                if offset_and_ts is not None:
                    self._consumer.seek(tp, offset_and_ts.offset)

    def process(self, message: dict) -> None:
        raise NotImplementedError

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f"kafka-{self.__class__.__name__}",
        )
        self._thread.start()
        logger.info("%s started on topic %s", self.__class__.__name__, self.topic)

    def stop(self):
        self._stop.set()
        if self._consumer:
            try:
                self._consumer.close(autocommit=True)
            except Exception:
                pass

    def _run(self):
        self._started_at = time.monotonic()
        while not self._stop.is_set():
            try:
                self._consumer = self._create_consumer()
                logger.info("%s connected to %s", self.__class__.__name__, self.topic)
                self._consume_loop()
            except ImportError:
                logger.debug("kafka-python not installed — %s disabled", self.__class__.__name__)
                return
            except Exception as e:
                logger.warning("%s consumer error: %s — reconnecting in 5s",
                               self.__class__.__name__, str(e)[:100])
                self._stop.wait(5)
            finally:
                if self._consumer:
                    try:
                        self._consumer.close(autocommit=True)
                    except Exception:
                        pass
                    self._consumer = None

    def _consume_loop(self):
        while not self._stop.is_set():
            try:
                for message in self._consumer:
                    if self._stop.is_set():
                        break
                    try:
                        self.process(message.value)
                        self._messages_processed += 1
                    except Exception as e:
                        self._errors += 1
                        logger.warning("%s process error: %s",
                                       self.__class__.__name__, str(e)[:100])
            except StopIteration:
                pass
            except Exception as e:
                if not self._stop.is_set():
                    logger.warning("%s poll error: %s", self.__class__.__name__, str(e)[:100])
                    self._stop.wait(1)

    @property
    def stats(self) -> dict:
        return {
            "worker": self.__class__.__name__,
            "topic": self.topic,
            "group_id": self.group_id,
            "messages_processed": self._messages_processed,
            "errors": self._errors,
            "alive": self._thread.is_alive() if self._thread else False,
            "uptime_s": round(time.monotonic() - self._started_at, 1) if self._started_at else 0,
        }
