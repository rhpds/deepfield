.PHONY: install test lint format clean db-up db-down

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest
VENV := venv

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -e ".[dev]"

test:
	cd backend && $(PYTEST) -v --tb=short

test-phase-1:
	cd backend && $(PYTEST) -v --tb=short app/tests/test_domain_models.py app/tests/test_synthetic_generator.py

test-phase-2:
	cd backend && $(PYTEST) -v --tb=short app/tests/test_benchmark_models.py app/tests/test_benchmark_generator.py app/tests/test_benchmark_runner.py

test-phase-3:
	cd backend && $(PYTEST) -v --tb=short app/tests/test_normalizer.py app/tests/test_nanoagents.py

test-phase-4:
	cd backend && $(PYTEST) -v --tb=short app/tests/test_signal_routing.py app/tests/test_correlation.py

test-phase-5:
	cd backend && $(PYTEST) -v --tb=short app/tests/test_mock_inference.py app/tests/test_inference_routing.py

test-phase-6:
	cd backend && $(PYTEST) -v --tb=short app/tests/test_capacity.py app/tests/test_reports.py

test-phase-7:
	cd backend && $(PYTEST) -v --tb=short app/tests/test_live_collector.py app/tests/test_e2e.py

lint:
	cd backend && $(PYTHON) -m ruff check app/

format:
	cd backend && $(PYTHON) -m ruff format app/

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

db-up:
	docker compose up -d postgres

db-down:
	docker compose down
