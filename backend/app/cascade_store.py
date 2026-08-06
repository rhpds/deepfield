"""Cascade persistent store — append-only audit trail in Postgres.

All cascade decisions, promotions, and state changes are recorded
in append-only tables. No UPDATE or DELETE — immutable by design.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://deepfield:deepfield2026x@deepfield-postgres:5432/deepfield")

_conn = None


def _get_conn():
    global _conn
    if _conn is not None:
        try:
            _conn.cursor().execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None

    try:
        import psycopg2
        _conn = psycopg2.connect(DATABASE_URL)
        _conn.autocommit = True
        _ensure_tables(_conn)
        log.info("Cascade store connected to Postgres")
        return _conn
    except Exception as e:
        log.warning("Cascade store: Postgres unavailable (%s), using memory only", str(e)[:60])
        return None


def _ensure_tables(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cascade_decisions (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            signal_type TEXT,
            severity TEXT,
            outcome TEXT,
            agent_name TEXT,
            evidence TEXT,
            namespace TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cascade_promotions (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            event TEXT,
            agent_name TEXT,
            from_tier TEXT,
            to_tier TEXT,
            accuracy REAL,
            samples INT,
            config JSONB
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cascade_state (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            state_type TEXT,
            data JSONB
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cascade_gate_fires (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            gate TEXT,
            signals_in_buffer INT,
            classified INT,
            low_confidence INT,
            noise_patterns JSONB
        )
    """)
    cur.close()


def log_decisions(decisions: list):
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        for d in decisions[:100]:
            cur.execute(
                "INSERT INTO cascade_decisions (signal_type, severity, outcome, agent_name, evidence, namespace) VALUES (%s,%s,%s,%s,%s,%s)",
                (d.get("signal_type", ""), d.get("severity", ""), d.get("outcome", ""),
                 d.get("agent_name", ""), d.get("evidence", "")[:200], d.get("namespace", "")),
            )
        cur.close()
    except Exception as e:
        log.debug("cascade_store log_decisions: %s", str(e)[:60])


def log_promotion(event: str, agent_name: str, from_tier: str, to_tier: str,
                   accuracy: float = 0, samples: int = 0, config: dict = None):
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO cascade_promotions (event, agent_name, from_tier, to_tier, accuracy, samples, config) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (event, agent_name, from_tier, to_tier, accuracy, samples, json.dumps(config or {})),
        )
        cur.close()
    except Exception as e:
        log.debug("cascade_store log_promotion: %s", str(e)[:60])


def log_gate_fire(gate: str, signals_in_buffer: int, classified: int,
                   low_confidence: int, noise_patterns: dict = None):
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO cascade_gate_fires (gate, signals_in_buffer, classified, low_confidence, noise_patterns) VALUES (%s,%s,%s,%s,%s)",
            (gate, signals_in_buffer, classified, low_confidence, json.dumps(noise_patterns or {})),
        )
        cur.close()
    except Exception as e:
        log.debug("cascade_store log_gate_fire: %s", str(e)[:60])


def save_state(state_type: str, data: dict):
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO cascade_state (state_type, data) VALUES (%s, %s)",
            (state_type, json.dumps(data)),
        )
        cur.close()
    except Exception as e:
        log.debug("cascade_store save_state: %s", str(e)[:60])


def load_latest_state(state_type: str) -> Optional[dict]:
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT data FROM cascade_state WHERE state_type = %s ORDER BY ts DESC LIMIT 1",
            (state_type,),
        )
        row = cur.fetchone()
        cur.close()
        if row:
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return None
    except Exception as e:
        log.debug("cascade_store load_state: %s", str(e)[:60])
        return None


def get_decision_summary(hours: int = 1) -> dict:
    conn = _get_conn()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT outcome, COUNT(*) FROM cascade_decisions
            WHERE ts > NOW() - INTERVAL '%s hours'
            GROUP BY outcome ORDER BY COUNT(*) DESC
        """, (hours,))
        rows = cur.fetchall()
        cur.close()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        log.debug("cascade_store get_summary: %s", str(e)[:60])
        return {}
