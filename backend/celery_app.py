"""Celery application for DeepField background task processing.

Replaces daemon threads with persistent, retryable, observable tasks.
Broker: Redis in ecosystem-redis namespace (DB 1).
"""

import os

from celery import Celery

REDIS_URL = os.environ.get(
    "CELERY_BROKER_URL",
    "redis://:ecosystem-redis-2026@redis.ecosystem-redis.svc:6379/1",
)

app = Celery("deepfield", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=100,
)

app.conf.beat_schedule = {
    "db-flush": {
        "task": "tasks.persistence.flush_to_db",
        "schedule": 5.0,
    },
    "prometheus-poll": {
        "task": "tasks.monitoring.poll_prometheus",
        "schedule": 30.0,
    },
}

app.autodiscover_tasks(["tasks"])

# Explicit imports to ensure tasks register with shared_task
import tasks.persistence  # noqa: F401, E402
import tasks.monitoring  # noqa: F401, E402
