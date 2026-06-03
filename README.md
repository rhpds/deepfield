# DeepField

Fleet-scale OpenShift signal intelligence and inference benchmarking platform.

Part of the **Launchpad + StarGate + DeepField** platform — three separate products that integrate via webhook events. DeepField is the observability plane.

**Core claim:** One Intel Xeon/Gaudi inference cluster can monitor **N** OpenShift clusters because deterministic nano-agent filters compress fleet telemetry so only a tiny percentage requires expensive LLM reasoning.

## The Proof

```
10,000,000 raw signals
    → nano-agent filters (deterministic, no LLM)
    → 12,000 correlated findings
    → 600 reasoning tasks routed to LLMs

Reasoning Compression Ratio: 16,666:1

Under this workload, one Intel Xeon 6 / Gaudi 3 inference cluster
can monitor an estimated N OpenShift clusters at p95 < S seconds.
```

## Role in the Platform

```
                    +-------------------+
                    | DeepField (you)   |   OBSERVABILITY
                    | Fleet signal intel|
                    | 14 nano-agents    |
                    +--------+----------+
                             |
                  monitors clusters that
                  Launchpad provisions on
                             |
+------------------+    +----v----------------+
|    StarGate      |    |     Launchpad       |   PROVISIONING + DEMOS
| Rubric evaluator |<-->| 17-state lifecycle  |
| Evidence bundles |    | Inference gateway   |
| Failure classes  |    | Workshop batching   |
+------------------+    +---------------------+
```

- **Launchpad** provisions demo environments and pushes lifecycle events to DeepField
- **StarGate** evaluates rubrics and pushes evaluation results to DeepField
- **DeepField** receives events from both, converts to signals, and processes through the nano-agent pipeline
- DeepField can suggest remediations back to Launchpad (session reset/reclaim)
- Each product deploys independently; integration is optional via env vars

## Architecture

```
Live K8s Watch (7 clusters) / Synthetic Generator / Integration Events
        ↓
Signal Normalizer → common schema
        ↓
Nano-Agent Filters (14) → deterministic, no LLM, fast
  - PodHealth, RouteHealth, PVCHealth, NodePressure, NamespaceQuota
  - KServeEndpoint, KafkaLag, LaunchpadSession, StarGateEvaluation
  - TransientSuppressor, Dedupe, EventClassifier, FailureClassifier
  - Adaptive cluster profiles (per-cluster noise/threshold learning)
        ↓
Signal Router → drop / keep / correlate / escalate
        ↓
Correlation Engine → namespace / cluster / cross-cluster grouping
        ↓
Inference Router → 7 models across Gaudi 3 + Xeon 6
  Macro tier (Gaudi): deepseek-r1-14b, phi-4, qwen3-14b (×2)
  Micro tier (Xeon):  phi3-mini, qwen25-3b, granite-2b
        ↓
Incident Manager → RCA parsing, classification, remediation
        ↓
EDD Rubrics → 5-dimension quality scoring (compression, classification, inference, coverage, safety)
        ↓
DB Persistence → PostgreSQL (signals, decisions, findings, inferences, incidents, profiles)
        ↓
Frontend → 12 pages, recharts, Tailwind dark theme
```

## Hardware

| Model | Hardware | Tier |
|-------|----------|------|
| DeepSeek-R1-Distill-Qwen-14B | Gaudi 3, 4 HPUs | Macro |
| Microsoft Phi-4 | Gaudi 3, 2 HPUs | Macro |
| Qwen3-14B (2 replicas) | Gaudi 3, 4 HPUs ×2 | Macro |
| Phi-3-Mini | Xeon 6 CPU | Micro |
| Qwen2.5-3B | Xeon 6 CPU | Micro |
| Granite-2B | Xeon 6 CPU | Micro |

All inference through LiteLLM/MAAS — no direct model endpoint calls.

## Quick Start

### Local Development

```bash
# Install
python3 -m venv venv && venv/bin/pip install -e ".[dev]"

# Run tests (203 tests)
cd backend && ../venv/bin/python -m pytest app/tests/ -v

# Start backend
export OCP_TOKEN=$(oc whoami -t)
cd backend && ../venv/bin/uvicorn app.main:app --port 8099

# Start frontend
cd frontend && npm install && npm run dev

# Open http://localhost:3100
```

### Deploy to OpenShift

```bash
# Login to your cluster
oc login --server=https://api.your-cluster.example.com:6443

# First run creates deploy/.secrets.env — edit with your values:
#   LITELLM_API_BASE — LiteLLM proxy URL for model inference
#   LITELLM_API_KEY  — API key for LiteLLM
#   CLUSTER_1_NAME   — Name of cluster to monitor
#   CLUSTER_1_API_URL — K8s API URL of monitored cluster
#   CLUSTER_1_TOKEN  — ServiceAccount token with cluster-reader role

# Deploy
cd deploy && ./deploy.sh --build
```

## Cluster Monitoring

DeepField monitors up to 20 clusters simultaneously via K8s watch API + periodic rescans. Each cluster is configured via environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `CLUSTER_N_NAME` | Yes | Display name (e.g., `infra01`) |
| `CLUSTER_N_API_URL` | Yes | K8s API URL |
| `CLUSTER_N_TOKEN` | Yes | SA token (cluster-reader role) |
| `CLUSTER_N_INCLUDE_NS` | No | Namespace include patterns (default: `*`) |
| `CLUSTER_N_EXCLUDE_NS` | No | Namespace exclude patterns (default: `openshift-*,kube-*`) |

Currently monitoring 7 clusters: `infra01`, `ocpv05`, `ocpv06`, `ocpv07`, `ocpv08`, `ocpv09`, `infra02`.

The collector emits signals only for unhealthy pods/nodes — healthy `pod_running` and `node_ready` are counted as infra stats without buffering full signal objects (memory optimization). Rescan dedup prevents re-emitting unchanged pod states.

## Adaptive Thresholding

Each cluster gets its own `ClusterProfile` that learns signal patterns and auto-tunes thresholds:

- **Dedup windows**: Auto-widen when a signal type exceeds 10× average rate (max 3600s)
- **Namespace noise scores**: EMA of suppression ratio per namespace
- **Dampen thresholds**: Auto-tighten when namespace noise > 90% (min 3)
- **Model health**: Per-model error rates and latency tracking

Profiles persist to PostgreSQL and reload on startup. The Tuning page shows all profiles with a cluster selector.

## Event Replay

Re-process historical Kafka signals through the current pipeline to validate tuning changes:

```
POST /api/v1/workers/replay  {from_timestamp, to_timestamp}
GET  /api/v1/workers/replay/{id}  → progress + results
POST /api/v1/workers/replay/{id}/stop
```

Replay uses a separate Kafka consumer group (`deepfield-replay-{id}`) and an in-memory `ReplayStore` — no DB writes, safe to run repeatedly. Results include agent summary, finding counts, and full EDD rubric evaluation.

## Integration

DeepField integrates with Launchpad and StarGate via webhook events. All integrations fail silently when targets are not configured.

| Direction | What | Endpoint |
|-----------|------|----------|
| Launchpad → DeepField | Session lifecycle events | `POST /integration/events` |
| StarGate → DeepField | Rubric evaluation results | `POST /integration/events` |
| DeepField → Launchpad | Remediation suggestions (reset/reclaim) | `POST {LAUNCHPAD_API_URL}/callbacks/remediation` |

Inbound events are converted to `RawSignal` objects and injected into the active session's nano-agent pipeline.

## Frontend

12 pages organized in 3 nav groups:

| Group | Page | Route | Purpose |
|-------|------|-------|---------|
| Monitor | Fleet Overview | `/` | Multi-cluster health, signal funnel, compression metrics |
| Monitor | Incidents | `/incidents` | RCA results, classification, remediation execution |
| Monitor | Live Flow | `/live` | Real-time signal stream |
| Pipeline | Agents | `/pipeline` | Nano-agent stats, decision log, Kafka worker status |
| Pipeline | LLM Models | `/llm` | Model performance, inference log, remediation UI |
| Quality | Rubrics | `/tuning` | EDD rubric scores, adaptive profile, cluster selector, threshold charts |
| Quality | Scenarios | `/scenarios` | Inject test signals for validation |
| Quality | Replay | `/replay` | Start/monitor historical signal replays |
| — | Cluster Detail | `/cluster/:id` | Per-cluster namespace breakdown |
| — | Simulator | `/simulator` | Synthetic signal generation controls |

Built with React 19, TypeScript, Tailwind CSS 4, recharts 3.8 for data visualization.

## Tech Stack

- **Python** >=3.11, **FastAPI** >=0.115, **Pydantic** >=2.10
- **Database:** asyncpg + PostgreSQL 16 (graceful degradation without DB, 7-day retention policy)
- **HTTP client:** httpx >=0.28 (outbound webhooks, K8s watch)
- **Frontend:** React 19, TypeScript 6, Vite 8, Tailwind 4, recharts 3.8
- **Container:** UBI9 base image, Podman
- **Deployment:** Kustomize + AgnosticV/AgnosticD + OpenShift

## Signal Types

DeepField processes 30+ signal types across 7 domains:

| Domain | Healthy | Warning | Failure |
|--------|---------|---------|---------|
| Pod | `pod_running` | `pod_pending` | `pod_crashloop`, `pod_imagepullbackoff` |
| Route | `route_ready` | — | `route_unhealthy` |
| Storage | `pvc_bound` | `pvc_pending` | — |
| Node | `node_ready` | — | `node_pressure` |
| Inference | `kserve_ready` | — | `kserve_not_ready` |
| Launchpad | `launchpad_lab_active` | `launchpad_lab_expired` | `launchpad_lab_failed` |
| StarGate | `stargate_stage_passed` | — | `stargate_stage_failed` |
| K8s Events | — | — | `event_backoff`, `event_failedscheduling`, `event_unhealthy`, ... |

## EDD Rubrics

5-dimension quality scoring, evaluated continuously:

| Rubric | Measures | Key Thresholds |
|--------|----------|----------------|
| Compression | Ratio, dedup rate, suppress rate, finding diversity | Ratio ≥50 healthy, ≥10 warning |
| Classification | JSON compliance, taxonomy match, naming consistency | ≥90% compliance healthy |
| Inference | Error rate, RCA depth, micro output, diversity | <5% errors healthy |
| Coverage | Namespaces, agents, signal types, critical detection | ≥30 namespaces healthy |
| Safety | Type suppression, cross-resource, critical dedup | 0 violations = healthy |

## Database

PostgreSQL 16 with 5 migrations, 7-day automatic retention on high-volume tables:

| Table | Purpose | Retention |
|-------|---------|-----------|
| `signals` | Raw actionable signals (medium+ severity) | 7 days |
| `decisions` | Nano-agent filter decisions | 7 days |
| `findings` | Correlated findings | 7 days |
| `inferences` | LLM call logs with prompts/outputs | 7 days |
| `incidents` | RCA incidents with classification | Permanent |
| `cluster_profiles` | Adaptive threshold state | Permanent (upsert) |
| `rubric_evaluations` | EDD evaluation history | 7 days |

## Tests

```
203 tests across 28 test files
Phase 1: Domain models + synthetic generator
Phase 2: Benchmark client + runner
Phase 3: Normalizer + 14 nano-agents
Phase 4: Correlation + signal routing
Phase 5: Inference routing + model metrics
Phase 6: Capacity projection + reports
Phase 7: E2E orchestrator + CLI + collectors
Phase 8: Kafka workers, replay, auth, remediation
```

## Key Files

```
backend/app/main.py                       — app startup, DB init, live monitoring auto-start
backend/app/db.py                         — async PostgreSQL, write queue, 7-day retention
backend/app/session/streaming_session.py  — live pipeline (watch → filter → correlate → infer)
backend/app/session/cluster_profile.py    — per-cluster adaptive thresholds
backend/app/session/signal_store.py       — in-memory signal/decision/finding store
backend/app/collectors/openshift.py       — K8s watch collector (read-only, dedup, infra counts)
backend/app/nanoagents/pipeline.py        — 14-agent filter pipeline
backend/app/correlation/engine.py         — namespace + cross-cluster correlation
backend/app/inference/adapters.py         — LiteLLM client (all models)
backend/app/inference/router.py           — macro/micro tier model routing
backend/app/api/session.py                — session API (live + synthetic)
backend/app/api/tuning.py                 — cluster profiles, EDD rubrics, proposals
backend/app/api/workers.py                — Kafka worker stats + replay management
backend/app/api/incidents.py              — incident lifecycle + remediation
backend/app/api/remediation.py            — suggest+confirm execution
backend/app/analysis/evaluator.py         — EDD rubric scoring
frontend/src/App.tsx                      — routing, nav groups (Monitor/Pipeline/Quality)
frontend/src/pages/FleetOverview.tsx      — multi-cluster health dashboard
frontend/src/pages/Tuning.tsx             — EDD rubrics + adaptive profiles + threshold charts
frontend/src/pages/Replay.tsx             — event replay controls + results
frontend/src/pages/Incidents.tsx          — RCA results + remediation execution
frontend/src/pages/SignalPipeline.tsx      — agent stats + decision log
```

## Key Metrics

- **Reasoning Compression Ratio** — raw_signals / reasoning_tasks
- **LLM Escalation Rate** — reasoning_tasks / raw_signals
- **Projected Fleet Coverage** — max_reasoning_tasks/min × compression_ratio / signals_per_cluster
- **Namespace Noise Score** — EMA of suppression ratio per namespace (0–100%)

## Principle

**Filter cheap. Reason expensive.**
