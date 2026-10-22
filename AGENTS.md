# DeepField

Fleet-scale OpenShift signal intelligence platform. Monitors up to 20 clusters simultaneously, compresses telemetry through 19 deterministic nano-agent filters (no LLM cost), and routes the remaining ~15% of signals to a five-lane LLM inference engine. Part of a three-product platform (Launchpad for provisioning, StarGate for evaluation, DeepField for monitoring).

## Quick Start

```bash
# Backend (port 8099)
python3 -m venv venv && venv/bin/pip install -e ".[dev]"
cd backend && ../venv/bin/uvicorn app.main:app --port 8099

# Frontend (port 3100, proxies /api to :8099)
cd frontend && npm install && npm run dev

# Database (optional -- app degrades gracefully without it)
make db-up  # postgres on port 5433
export DATABASE_URL=postgresql://deepfield:devpass123@localhost:5433/deepfield

# Container
podman build -f Containerfile -t deepfield .
```

## Testing

```bash
make test              # All tests (203+ across 28+ files)
make test-phase-1      # Domain models + synthetic generator
make test-phase-2      # Benchmark client + runner
# ... through phase-7
make lint              # ruff check
make format            # ruff format
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`.

## File Structure

| Directory | Purpose |
|-----------|---------|
| `backend/app/main.py` | FastAPI app + lifespan (DB init, live monitoring, Kafka workers) |
| `backend/app/domain/models.py` | Pydantic v2 domain models |
| `backend/app/nanoagents/` | 19 deterministic filters in 3 stages (noise/infrastructure/application) |
| `backend/app/inference/` | Three-tier model routing (nano/micro/macro), LiteLLM adapter |
| `backend/app/session/` | Core pipeline: streaming, cluster profiles, signal store, incidents |
| `backend/app/collectors/` | K8s watch API (read-only), multi-cluster, Splunk, AlertManager, Prometheus, synthetic |
| `backend/app/api/` | 14 FastAPI routers |
| `backend/app/agents/` | Higher-level LLM agents (triage, RCA, correlation, incident, remediation) |
| `backend/app/workers/` | Kafka workers (nano-agent, correlation, inference, replay) |
| `backend/intel-inference-router/` | Semi-independent sub-package: five-lane inference routing engine (own pyproject.toml) |
| `frontend/` | React 19 + TypeScript + Tailwind 4 + Vite dashboard (12 pages, recharts) |
| `deploy/` | OpenShift Kustomize manifests + deploy.sh |

## Architecture

```
Signal Ingestion (K8s watch / synthetic)
  -> Normalization (RawSignal -> NormalizedSignal)
  -> Nano-agent Pipeline (19 filters, 3 stages, compresses 85-92%)
  -> Signal Routing (drop/keep/correlate)
  -> Correlation Engine (namespace + cross-cluster)
  -> Inference Router (nano/micro/macro tiers, 5 lanes)
  -> Incident Management (RCA, classification, remediation)
```

Persistence: PostgreSQL 16 via asyncpg (raw SQL, not SQLAlchemy) with 7-day retention on high-volume tables.

## Key Conventions

- Python 3.11+, FastAPI, Pydantic v2, asyncpg (not SQLAlchemy)
- Ruff for lint/format (line length 120, E501 ignored for prompt strings)
- Graceful degradation everywhere: DB optional, Kafka optional, integrations fail silently
- Threading for background work (collectors, workers, session loops)
- All inference through LiteLLM/MaaS proxy (no direct model calls)
- Frontend: lazy-loaded pages, @tanstack/react-query, dark theme
- Multi-cluster config via env vars: `CLUSTER_N_NAME`, `CLUSTER_N_API_URL`, `CLUSTER_N_TOKEN` (up to 20)
- Backend port: 8099, frontend dev port: 3100
