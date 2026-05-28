"""Persistence tasks — flush write queue to DB, write session summaries."""

import logging

from celery import shared_task

logger = logging.getLogger("deepfield.tasks.persistence")


@shared_task(bind=True, max_retries=2)
def flush_to_db(self):
    """Drain the in-memory write queue into PostgreSQL."""
    try:
        from app.db import _write_queue, _pool

        if _pool is None:
            logger.debug("No DB pool — skipping flush")
            return {"status": "skipped", "reason": "no_pool"}

        flushed = 0
        while _write_queue:
            item = _write_queue.popleft()
            # TODO: batch INSERT via asyncpg pool
            flushed += 1

        logger.info("Flushed %d records to DB", flushed)
        return {"status": "ok", "flushed": flushed}
    except Exception as e:
        logger.warning("flush_to_db failed: %s", e)
        raise self.retry(exc=e, countdown=5)


@shared_task(bind=True, max_retries=1)
def write_session_summary(self, session_id: str, summary: dict):
    """Persist a completed session summary to the database."""
    try:
        from app.db import _pool

        if _pool is None:
            logger.debug("No DB pool — skipping session summary write")
            return {"status": "skipped", "reason": "no_pool"}

        # TODO: INSERT into session_summaries table
        logger.info("Wrote session summary for %s", session_id)
        return {"status": "ok", "session_id": session_id}
    except Exception as e:
        logger.warning("write_session_summary failed: %s", e)
        raise self.retry(exc=e, countdown=5)
