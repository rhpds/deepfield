import sys
from types import SimpleNamespace

from app import db


class FakeConnection:
    def __init__(self, failure_table=None):
        self.failure_table = failure_table
        self.queries = []
        self.closed = False

    async def execute(self, query):
        self.queries.append(query)
        if self.failure_table and f"DELETE FROM {self.failure_table} " in query:
            raise RuntimeError("retention failure")
        return "DELETE 1"

    async def close(self):
        self.closed = True


def _run_retention(monkeypatch, connection):
    async def connect(_url):
        return connection

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    db._run_retention_sync("postgresql://test")


def test_retention_uses_each_tables_real_timestamp_column(monkeypatch):
    connection = FakeConnection()

    _run_retention(monkeypatch, connection)

    assert connection.closed
    assert len(connection.queries) == len(db._RETENTION_TABLES)
    for table, timestamp_column in db._RETENTION_TABLES.items():
        assert any(
            f"DELETE FROM {table} WHERE {timestamp_column} <" in query
            for query in connection.queries
        )


def test_retention_logs_table_failure_and_continues(monkeypatch, caplog):
    connection = FakeConnection(failure_table="signals")

    _run_retention(monkeypatch, connection)

    assert len(connection.queries) == len(db._RETENTION_TABLES)
    assert "Retention cleanup failed for signals" in caplog.text
