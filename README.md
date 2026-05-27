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
                    | 12 nano-agents    |
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
Synthetic Generator / Live Collector / Integration Events
        ↓
Signal Normalizer → common schema
        ↓
Nano-Agent Filters (12) → deterministic, no LLM, fast
  - PodHealth, RouteHealth, PVCHealth, NodePressure, NamespaceQuota
  - KServeEndpoint, KafkaLag, LaunchpadSession, StarGateEvaluation
  - TransientSuppressor, Dedupe, EventClassifier
        ↓
Signal Router → drop / keep / correlate / escalate
        ↓
Correlation Engine → namespace / cluster / cross-cluster grouping
        ↓
Inference Router → phi4 fast / qwen3 general / deepseek reasoning / llama70b baseline
        ↓
Benchmark Client → token cannon / model race / saturation curve
        ↓
Metrics + Reports → signal funnel, compression ratio, capacity projection
```

## Hardware

| Model | Hardware | Endpoint |
|-------|----------|----------|
| DeepSeek-R1-Distill-Qwen-14B | Gaudi 3, 4 HPUs | Direct KServe |
| Microsoft Phi-4 | Gaudi 3, 2 HPUs | Direct KServe |
| Qwen3-14B (2 replicas) | Gaudi 3, 4 HPUs x2 | Direct KServe |
| Llama 3.1 70B Q4 | Xeon 6767P CPU | Direct KServe |

## Quick Start

### Local Development

```bash
# Install
python3 -m venv venv && venv/bin/pip install -e ".[dev]"

# Run tests (124 tests)
cd backend && ../venv/bin/python -m pytest app/tests/ -v

# Start backend
export OCP_TOKEN=$(oc whoami -t)
cd backend && ../venv/bin/uvicorn app.main:app --port 8099

# Start frontend
cd frontend && npm install && npm run dev

# Open http://localhost:3100
```

### CLI

```bash
# Synthetic fleet run
cd backend && ../venv/bin/python -m app.cli run-synthetic --profile small --seed 42

# Benchmark (mock)
cd backend && ../venv/bin/python -m app.cli benchmark --profile model_race --mode mock --seed 42

# Capacity projection
cd backend && ../venv/bin/python -m app.cli capacity-report --profile small --seed 42
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

## Integration

DeepField integrates with Launchpad and StarGate via webhook events. All integrations fail silently when targets are not configured.

| Direction | What | Endpoint |
|-----------|------|----------|
| Launchpad → DeepField | Session lifecycle events | `POST /integration/events` |
| StarGate → DeepField | Rubric evaluation results | `POST /integration/events` |
| DeepField → Launchpad | Remediation suggestions (reset/reclaim) | `POST {LAUNCHPAD_API_URL}/callbacks/remediation` |

Inbound events are converted to `RawSignal` objects and injected into the active session's nano-agent pipeline. Launchpad events become `launchpad_lab_*` signals processed by the `LaunchpadSessionAgent`. StarGate events become `stargate_stage_*` signals processed by the `StarGateEvaluationAgent`.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LAUNCHPAD_API_URL` | No | Launchpad base URL for pushing remediation suggestions. |
| `LAUNCHPAD_API_KEY` | No | API key for Launchpad authentication. |

### Shared Event Schema

All three products use the same envelope:

```json
{
  "source": "launchpad|stargate|deepfield",
  "event_type": "session_lifecycle|evaluation_result|...",
  "event_id": "uuid",
  "timestamp": "ISO 8601",
  "payload": {}
}
```

## Tech Stack

- **Python** >=3.11, **FastAPI** >=0.115, **Pydantic** >=2.10
- **Database:** asyncpg + PostgreSQL (graceful degradation without DB)
- **HTTP client:** httpx >=0.28 (outbound webhooks)
- **Frontend:** React 19, TypeScript 6, Vite 8, Tailwind 4
- **Container:** UBI9 base image, Podman
- **Deployment:** Kustomize + AgnosticV/AgnosticD + OpenShift

## Signal Types

DeepField processes 30 signal types across 6 domains:

| Domain | Healthy | Warning | Failure |
|--------|---------|---------|---------|
| Pod | `pod_running` | `pod_pending` | `pod_crashloop`, `pod_imagepullbackoff` |
| Route | `route_ready` | — | `route_unhealthy` |
| Storage | `pvc_bound` | `pvc_pending` | — |
| Node | `node_ready` | — | `node_pressure` |
| Inference | `kserve_ready` | — | `kserve_not_ready` |
| Launchpad | `launchpad_lab_active` | `launchpad_lab_expired` | `launchpad_lab_failed` |
| StarGate | `stargate_stage_passed`, `stargate_run_completed` | — | `stargate_stage_failed` |

## Benchmark Profiles

| Profile | Requests | Models | Concurrency | Purpose |
|---------|----------|--------|-------------|---------|
| `endpoint_sanity` | 15 | All | 1 | Verify endpoints respond |
| `gaudi_race` | 60 | Gaudi only | 1→8→25 | Ramp concurrency on Gaudi 3 |
| `gaudi_blast` | 200 | Gaudi only | 25→50 | Max Gaudi throughput |
| `full_fleet` | 100 | All (Gaudi+Xeon) | 10→25 | Full hardware comparison |
| `token_cannon` | 80 | Gaudi only | 4→8→16 | Output-heavy, 2K tokens |
| `model_race` | 50 | All | 1→8 | Same prompts, compare models |
| `reasoning_gauntlet` | 30 | DeepSeek+Qwen3 | 1→4→8 | RCA + reasoning tasks |
| `saturation_curve` | 100 | All | 1→2→4→...→128 | Find breaking point |

## Key Metrics

- **Reasoning Compression Ratio** — raw_signals / reasoning_tasks
- **LLM Escalation Rate** — reasoning_tasks / raw_signals
- **Projected Fleet Coverage** — max_reasoning_tasks/min x compression_ratio / signals_per_cluster
- **Stable Model Throughput** — highest concurrency where p95 < target and error rate < threshold

## Tests

```
124 tests across 14 test files
Phase 1: Domain models + synthetic generator
Phase 2: Benchmark client + runner
Phase 3: Normalizer + 12 nano-agents (including LaunchpadSession + StarGateEvaluation)
Phase 4: Correlation + signal routing
Phase 5: Inference routing + model metrics
Phase 6: Capacity projection + reports
Phase 7: E2E orchestrator + CLI + collectors
```

## Principle

**Filter cheap. Reason expensive.**
