# DeepField

Fleet-scale OpenShift signal intelligence and inference benchmarking platform.

Part of the **Launchpad + StarGate + DeepField** platform — three separate products that integrate via webhook events. DeepField is the observability plane.

**Core claim:** One Intel Xeon server can monitor **20+ OpenShift clusters** because deterministic nano-agent filters compress fleet telemetry so only 15% requires model inference, and five-lane routing sends each task to the right-sized model.

## The Proof (Oberon Soak Test)

```
30,000,000 signals/day
    --> 19 nano-agent filters (deterministic, zero cost)
    --> 85% handled by rules, 15% need inference
    --> Five-lane routing: classification (88ms) | extraction (3s)
                          | generation (5s) | reasoning (10s)
    --> 38.6 GB memory, 8% of Xeon 503 GB server

Validated: 1-hour soak test, zero errors on live models,
           full recovery from 64-core CPU stress test.
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
Live K8s Watch (20 clusters) / Synthetic Generator / Integration Events
        |
        v
Signal Normalizer --> common schema
        |
        v
Nano-Agent Filters (19) --> deterministic, no LLM, zero cost
  Stage 1: Noise (Dedupe, Transient, InfraNoise)
  Stage 2: Infrastructure (Pod, Route, PVC, Node, Quota, KServe, Kafka, Launchpad, StarGate)
  Stage 3: Application (AppLog, Alert, Security, Provisioning, Network)
        |
        v                          +----------------------------------+
Signal Router                      | Workload Bootstrapper            |
  drop / keep / correlate         | Detects workload type from       |
        |                          | signal patterns (cosine sim)     |
        v                          +----------------+-----------------+
Correlation Engine                                  |
  namespace / cluster /                             v
  cross-cluster grouping           +----------------------------------+
        |                          | Strategy Router                  |
        v                          | Picks inference pattern per      |
                                   | workload (cascade, INT8, etc.)   |
+-------------------------------+  +----------------+-----------------+
| Five-Lane Inference Router    |                   |
| (intel-inference-router)      |<------------------+
|                               |
|  Classification:  smollm2-360m, granite-350m       (88ms, 40+ tok/s)
|  Extraction:      granite-2b, qwen25-3b            (3-5s)
|  Generation:      phi3-mini, qwen25-3b             (3-8s)
|  Reasoning:       qwen36-moe-35b (MoE)             (5-18s)
|  Embedding:       (scaffold)                        (<10ms)
+-------------------------------+
        |
        v
Incident Manager --> RCA parsing, classification, remediation
        |
        v
+-------------------------------+    +----------------------------------+
| Pressure Scaler               |    | Fleet Manager                    |
| Monitors /proc/pressure       |    | Scales model replicas by lane    |
| Sheds models under load       |    | granite-350m x8, MoE x1, etc.   |
| Rubric-graded (R/Y/G)        |    | FleetScorecard (R/Y/G)           |
+-------------------------------+    +----------------------------------+
        |
        v
EDD Rubrics --> 8-dimension quality scoring
  1. Compression quality        5. Tuning safety
  2. Classification accuracy    6. Routing quality
  3. Inference value            7. Fleet health
  4. Signal coverage            8. Classification live
        |
        v
DB Persistence --> PostgreSQL (async, graceful degradation)
        |
        v
Frontend --> 12 pages, recharts, Tailwind dark theme
```

### Key Numbers (from Oberon soak test)

| Metric | Value |
|--------|-------|
| Signal capacity | 30M signals/day |
| Cascade compression | 85-92% handled by nano-rules (zero inference cost) |
| Classification throughput | 200+ tok/s aggregate (8 replicas, 5.6 GB) |
| Classification latency | 88ms p95 (isolated), 700ms under contention |
| Memory footprint | 38.6 GB for full five-lane deployment |
| Xeon utilization | 8% of 503 GB server |
| Models supported | 19 across OVMS, vLLM, llama-cpp |
| Stress test | Zero errors through 64-core CPU stress, full recovery |

### Event Flow: One Signal's Journey

```
1. K8s watch detects pod_crashloop in namespace fraud-scoring
   |
2. Normalizer: severity=high, resource_kind=Pod, confidence=0.95
   |
3. Nano pipeline (19 agents):
   - Dedupe: not seen in 60s window --> keep
   - FailureClassifier: matches "pods_crashlooping" --> enrich
   - PodHealth: severity=high --> escalate
   |
4. Signal Router: escalated + high severity --> keep for correlation
   |
5. Bootstrapper observes signal:
   - Window has 30 signals matching fraud-triage fingerprint
   - Cosine similarity = 0.82 --> workload_type = "fraud-triage"
   |
6. Correlator: groups with 2 other signals in same namespace
   - Creates CandidateFinding (severity=high, 3 signals)
   |
7. Strategy Router: fraud-triage --> routing_ladder_int8 (grade=green)
   |
8. Lane Router: task=root_cause_analysis --> reasoning lane
   - Model: qwen36-moe-35b-a3b (35B MoE, 15 tok/s)
   |
9. LiteLLM proxy --> llama-qwen36-moe.triforce.svc:8080
   |
10. Inference result: root cause analysis with remediation steps
    |
11. Incident Manager: creates/updates incident, stores in PostgreSQL
    |
12. EDD Evaluator grades: routing=healthy, fleet=healthy, classification=green
```

## Hardware (Oberon Cluster)

| Lane | Model | Params | Backend | Replicas | Memory |
|------|-------|--------|---------|----------|--------|
| Classification | smollm2-360m | 360M | llama-cpp | 4 | 2.0 GB |
| Classification | granite-350m | 350M | OVMS | 8 | 7.2 GB |
| Extraction | granite-2b-cpu | 2B | OVMS | 1 | 5.2 GB |
| Extraction | qwen25-3b-cpu | 3B | OVMS | 1 | 7.8 GB |
| Generation | phi3-mini-cpu | 3.8B | OVMS | 1 | 9.9 GB |
| Reasoning | qwen36-moe-35b | 35B/3B active | llama-cpp | 1 | 20 GB |
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
