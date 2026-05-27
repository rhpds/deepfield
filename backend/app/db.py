"""Async database connection with graceful degradation.

Works identically without a database — all queries return empty results.
When DATABASE_URL is set, connects to PostgreSQL and runs migrations.
"""

import os
import json
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_pool = None
_write_queue: deque = deque(maxlen=5000)
_writer_thread: Optional[threading.Thread] = None
_writer_stop = threading.Event()


async def init_db():
    global _pool
    url = os.getenv("DATABASE_URL")
    if not url:
        logger.info("DATABASE_URL not set — running without persistence")
        return

    try:
        import asyncpg
        _pool = await asyncpg.create_pool(url, min_size=2, max_size=10)
        await _run_migrations()
        _start_writer()
        logger.info("Database connected and migrations applied")
    except Exception as e:
        logger.warning("Database init failed (continuing without persistence): %s", str(e)[:200])
        _pool = None


async def close_db():
    global _pool
    _writer_stop.set()
    if _pool:
        await _pool.close()
        _pool = None


async def _run_migrations():
    if not _pool:
        return
    migrations_dir = Path(__file__).parent.parent / "migrations"
    if not migrations_dir.exists():
        return

    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        applied = {r["filename"] for r in await conn.fetch("SELECT filename FROM applied_migrations")}

        for sql_file in sorted(migrations_dir.glob("*.sql")):
            if sql_file.name not in applied:
                logger.info("Applying migration: %s", sql_file.name)
                sql = sql_file.read_text()
                statements = [s.strip() for s in sql.split(";\n") if s.strip() and not s.strip().startswith("--")]
                for stmt in statements:
                    try:
                        await conn.execute(stmt)
                    except Exception as e:
                        logger.warning("Migration statement failed: %s: %s", stmt[:80], str(e)[:100])


async def query(sql: str, *args) -> list:
    if not _pool:
        return []
    try:
        rows = await _pool.fetch(sql, *args)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("DB query failed: %s", str(e)[:200])
        return []


async def execute(sql: str, *args):
    if not _pool:
        return
    try:
        await _pool.execute(sql, *args)
    except Exception as e:
        logger.warning("DB execute failed: %s", str(e)[:200])


def enqueue_write(table: str, data: dict):
    """Non-blocking write — enqueues for background batch insert."""
    _write_queue.append((table, data))


def _start_writer():
    global _writer_thread
    _writer_stop.clear()
    _writer_thread = threading.Thread(target=_writer_loop, daemon=True)
    _writer_thread.start()


def _writer_loop():
    """Background thread that batches and writes queued data to the database."""
    import asyncpg

    _db_url = os.getenv("DATABASE_URL", "")
    if not _db_url:
        return

    while not _writer_stop.is_set():
        batch = []
        while _write_queue and len(batch) < 50:
            try:
                batch.append(_write_queue.popleft())
            except IndexError:
                break

        if batch:
            _flush_batch_sync(batch, _db_url)

        _writer_stop.wait(1.0)


def _flush_batch_sync(batch: list, db_url: str):
    """Synchronous batch write using a dedicated connection per flush."""
    import asyncio
    import asyncpg

    async def _do_flush():
        try:
            conn = await asyncpg.connect(db_url)
            try:
                by_table: dict = {}
                for table, data in batch:
                    by_table.setdefault(table, []).append(data)

                for table, rows in by_table.items():
                    for row in rows:
                        cols = list(row.keys())
                        vals = []
                        for c in cols:
                            v = row[c]
                            if isinstance(v, (dict, list)):
                                vals.append(json.dumps(v))
                            else:
                                vals.append(v)
                        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
                        col_names = ", ".join(cols)
                        await conn.execute(
                            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                            *vals,
                        )
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("DB batch write failed: %s", str(e)[:200])

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_do_flush())
    finally:
        loop.close()
