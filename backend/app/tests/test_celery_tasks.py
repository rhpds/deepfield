"""Celery tasks — TDD."""
import pytest


class TestCeleryApp:
    def test_celery_app_exists(self):
        from celery_app import app
        assert app.main == "deepfield"

    def test_beat_schedule(self):
        from celery_app import app
        assert "db-flush" in app.conf.beat_schedule
        assert "prometheus-poll" in app.conf.beat_schedule

    def test_broker_configured(self):
        from celery_app import app
        assert "redis" in app.conf.broker_url or "memory" in app.conf.broker_url


class TestTaskModules:
    def test_persistence_tasks(self):
        from tasks.persistence import flush_to_db, write_session_summary
        assert callable(flush_to_db)
        assert callable(write_session_summary)

    def test_monitoring_tasks(self):
        from tasks.monitoring import poll_prometheus
        assert callable(poll_prometheus)
