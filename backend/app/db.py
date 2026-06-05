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
_write_queue: deque = deque(maxlen=100000)
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


_ALLOWED_TABLES = frozenset({
    "signals", "decisions", "findings", "inferences", "remediations",
    "agent_stats_snapshots", "session_snapshots", "metrics_snapshots",
    "cluster_profiles", "rubric_evaluations", "incidents",
})


def enqueue_write(table: str, data: dict):
    """Non-blocking write — enqueues for background batch insert."""
    if table not in _ALLOWED_TABLES:
        logger.warning("Rejected write to unknown table: %s", table)
        return
    qlen = len(_write_queue)
    if qlen > 80000:
        logger.warning("Write queue near capacity: %d/100000", qlen)
    _write_queue.append((table, data))


def get_queue_depth() -> int:
    return len(_write_queue)


def _start_writer():
    global _writer_thread
    _writer_stop.clear()
    _writer_thread = threading.Thread(target=_writer_loop, daemon=True, name="db-writer")
    _writer_thread.start()


_RETENTION_DAYS = int(os.getenv("DB_RETENTION_DAYS", "7"))
_RETENTION_TABLES = ("signals", "decisions", "inferences", "findings",
                     "metrics_snapshots", "session_snapshots", "agent_stats_snapshots")


def _writer_loop():
    """Background thread that batches and writes queued data to the database."""
    _db_url = os.getenv("DATABASE_URL", "")
    if not _db_url:
        return

    import time as _time
    _last_retention = _time.monotonic()
    _last_mv_refresh = _time.monotonic()
    _RETENTION_INTERVAL = 3600
    _MV_REFRESH_INTERVAL = 300

    while not _writer_stop.is_set():
        batch = []
        while _write_queue and len(batch) < 2000:
            try:
                batch.append(_write_queue.popleft())
            except IndexError:
                break

        if batch:
            _flush_batch_sync(batch, _db_url)

        if _time.monotonic() - _last_retention >= _RETENTION_INTERVAL:
            _run_retention_sync(_db_url)
            _last_retention = _time.monotonic()

        if _time.monotonic() - _last_mv_refresh >= _MV_REFRESH_INTERVAL:
            _refresh_materialized_views_sync(_db_url)
            _last_mv_refresh = _time.monotonic()

        _writer_stop.wait(0.2)


def _refresh_materialized_views_sync(db_url: str):
    """Refresh pre-computed metrics views for dashboard performance."""
    import asyncio, asyncpg

    async def _do():
        try:
            conn = await asyncpg.connect(db_url)
            try:
                for window, interval in [("15m", "15 minutes"), ("1h", "1 hour"), ("24h", "24 hours")]:
                    try:
                        await conn.execute(f"""
                            INSERT INTO mv_metrics_funnel (window_label, total_signals, high_severity, medium_severity,
                                total_decisions, total_findings, total_inferences, compression_ratio, updated_at)
                            VALUES ('{window}',
                                COALESCE((SELECT count(*) FROM signals WHERE captured_at >= now() - interval '{interval}'), 0),
                                COALESCE((SELECT count(*) FROM signals WHERE captured_at >= now() - interval '{interval}' AND severity = 'high'), 0),
                                COALESCE((SELECT count(*) FROM signals WHERE captured_at >= now() - interval '{interval}' AND severity = 'medium'), 0),
                                COALESCE((SELECT count(*) FROM decisions WHERE captured_at >= now() - interval '{interval}'), 0),
                                COALESCE((SELECT count(*) FROM findings WHERE captured_at >= now() - interval '{interval}'), 0),
                                COALESCE((SELECT count(*) FROM inferences WHERE captured_at >= now() - interval '{interval}'), 0),
                                0, now())
                            ON CONFLICT (window_label) DO UPDATE SET
                                total_signals = EXCLUDED.total_signals, high_severity = EXCLUDED.high_severity,
                                medium_severity = EXCLUDED.medium_severity, total_decisions = EXCLUDED.total_decisions,
                                total_findings = EXCLUDED.total_findings, total_inferences = EXCLUDED.total_inferences,
                                updated_at = EXCLUDED.updated_at
                        """)
                    except Exception:
                        pass
                logger.info("Materialized views refreshed")
            finally:
                await conn.close()
        except Exception as e:
            logger.debug("MV refresh failed: %s", str(e)[:100])

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_do())
    finally:
        loop.close()


def _run_retention_sync(db_url: str):
    """Delete rows older than _RETENTION_DAYS from high-volume tables."""
    import asyncio, asyncpg
    async def _do():
        try:
            conn = await asyncpg.connect(db_url)
            try:
                for table in _RETENTION_TABLES:
                    try:
                        result = await conn.execute(
                            f"DELETE FROM {table} WHERE captured_at < now() - interval '{_RETENTION_DAYS} days'"
                        )
                        if result and result != "DELETE 0":
                            logger.info("Retention cleanup %s: %s", table, result)
                    except Exception as e:
                        logger.debug("Retention skip %s: %s", table, str(e)[:80])
            finally:
                await conn.close()
        except Exception as e:
            logger.debug("Retention connect failed: %s", str(e)[:100])
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_do())
    finally:
        loop.close()


def _coerce_value(col: str, val):
    """Fix type mismatches before DB insert."""
    if col in ("namespaces", "clusters"):
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                return [val]
        if isinstance(val, list):
            return val
    if isinstance(val, dict):
        return json.dumps(val)
    if isinstance(val, list):
        return json.dumps(val)
    return val


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

                import re
                _COL_RE = re.compile(r'^[a-z_][a-z0-9_]*$')
                upsert_tables = {"cluster_profiles": "cluster_id", "incidents": "id"}

                for table, rows in by_table.items():
                    if table not in _ALLOWED_TABLES:
                        continue

                    cols = list(rows[0].keys())
                    if not all(_COL_RE.match(c) for c in cols):
                        logger.warning("Rejected batch with invalid column names: %s", cols)
                        continue

                    if table in upsert_tables:
                        pk = upsert_tables[table]
                        for row in rows:
                            vals = [_coerce_value(c, row.get(c)) for c in cols]
                            placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
                            col_names = ", ".join(cols)
                            update_cols = [c for c in cols if c != pk]
                            update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
                            sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT ({pk}) DO UPDATE SET {update_set}"
                            try:
                                await conn.execute(sql, *vals)
                            except Exception as e:
                                logger.warning("DB upsert %s failed: %s", table, str(e)[:150])
                    else:
                        col_names = ", ".join(cols)
                        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
                        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
                        prepared_rows = []
                        for row in rows:
                            try:
                                prepared_rows.append(tuple(_coerce_value(c, row.get(c)) for c in cols))
                            except Exception as e:
                                logger.warning("DB row prep %s failed: %s", table, str(e)[:100])
                        if prepared_rows:
                            try:
                                await conn.executemany(sql, prepared_rows)
                            except Exception as e:
                                logger.warning("DB batch insert %s (%d rows) failed: %s — falling back to individual", table, len(prepared_rows), str(e)[:150])
                                for vals in prepared_rows:
                                    try:
                                        await conn.execute(sql, *vals)
                                    except Exception:
                                        pass
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("DB batch connect failed: %s", str(e)[:200])

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_do_flush())
    finally:
        loop.close()
