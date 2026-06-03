# DeepField — TODO

## What It Is

Fleet-scale OpenShift signal intelligence. Watches real clusters, compresses K8s telemetry through deterministic nano-agent filters, routes only the important signals to LLMs on Intel Gaudi 3 / Xeon 6 for root cause analysis with structured remediation. Proves one inference cluster can monitor hundreds of OpenShift clusters.

```
K8s Watch (7 clusters) → 14 Nano Agents (deterministic) → Correlation → Micro (Xeon 6) / Macro (Gaudi 3) → RCA + Remediation → PostgreSQL
```

## Status: What Works

- [x] Live monitoring auto-starts at pod startup, watches 7 configured clusters
- [x] K8s watch API + periodic 30s rescans with dedup (no duplicate signals for unchanged state)
- [x] Memory-optimized collector: healthy pods/nodes counted as stats, not buffered as signals
- [x] 14 nano-agents (PodHealth, RouteHealth, PVCHealth, NodePressure, NamespaceQuota, KServeEndpoint, KafkaLag, LaunchpadSession, StarGateEvaluation, TransientSuppressor, Dedupe, EventClassifier, FailureClassifier, + adaptive profile-aware pipeline)
- [x] Per-cluster adaptive profiles: auto-tuning dedup windows, namespace noise scores, dampen thresholds
- [x] Correlation engine groups by namespace and cross-cluster
- [x] 7 inference models: 4 Gaudi (macro), 3 Xeon (micro), all through LiteLLM/MAAS
- [x] Structured RCA: per-signal evidence (resource names, exit codes, restart counts, owner refs, node names, event messages)
- [x] Structured JSON output (root_cause, category, evidence_chain, confidence, remediation)
- [x] Incident manager: signal→finding→RCA→classification→remediation lifecycle
- [x] Remediation suggest+confirm with click-to-execute and audit trail
- [x] PostgreSQL persistence with 7-day auto-retention on high-volume tables
- [x] EDD rubric evaluation: 5 dimensions (compression, classification, inference, coverage, safety)
- [x] Event replay: re-process historical Kafka data through current pipeline without DB writes
- [x] 12-page frontend: Fleet Overview, Incidents, Live Flow, Agents, LLM Models, Rubrics (with cluster selector + recharts), Scenarios, Replay, Cluster Detail, Simulator
- [x] ServiceAccount tokens (1-year, cluster-reader) for monitoring
- [x] Repo sanitized — zero hardcoded internal URLs, tokens, or cluster names
- [x] agnosticd/agnosticv CI packaging (matches Launchpad pattern)
- [x] Apache 2.0 license
- [x] 203 tests passing across 28 test files

## TODO: Active

- [ ] **Per-cluster pipeline separation** — currently all 7 clusters feed into one merged pipeline. Per-cluster profiling works (each gets its own profile) but decisions/findings aren't bucketed per cluster in the pipeline itself.
- [ ] **Evaluation history accumulation** — history chart needs ≥3 data points; evaluation snapshots need to accumulate faster (currently one per 5-min cache TTL).
- [ ] **Push image to quay.io** — currently in OCP internal registry. Need `quay.io/intel-redhat/deepfield:latest` for CI.
- [ ] **Re-enable OAuth/SSO** — disabled during development.
- [ ] **Prometheus GPU utilization charts** — Thanos/Prometheus poller exists but not wired to frontend charts.

## TODO: Polish

- [ ] Historical data timeline in UI (DB has data, no time-range query view yet)
- [ ] Finding → inference ID linkage in database
- [ ] Rate limiting on remediation execution
- [ ] Replay results comparison (A/B between two replays or replay vs live)
- [ ] Tuning proposal auto-generation from evaluation deltas

## Architecture

| Component | Location | Tech |
|-----------|----------|------|
| Backend | `deepfield` namespace | Python 3.11, FastAPI, uvicorn |
| Frontend | Bundled with backend (Vite build → static/) | React 19, TypeScript, Tailwind 4, recharts |
| Database | Same namespace | PostgreSQL 16, 10Gi PVC, 7-day retention |
| Inference (GPU) | LiteLLM/MAAS | deepseek-r1-14b, phi-4, qwen3-14b (×2) on Gaudi 3 |
| Inference (CPU) | LiteLLM/MAAS | phi3-mini, qwen25-3b, granite-2b on Xeon 6 |
| Monitoring | Read-only K8s Watch + Prometheus | 7 clusters, configurable via env vars (up to 20) |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LITELLM_API_BASE` | Yes | LiteLLM proxy URL |
| `LITELLM_API_KEY` | Yes | LiteLLM API key |
| `DATABASE_URL` | No | PostgreSQL connection (works without) |
| `DB_RETENTION_DAYS` | No | Days to keep high-volume table data (default: 7) |
| `CLUSTER_N_NAME` | Yes | Monitored cluster name (N = 1–20) |
| `CLUSTER_N_API_URL` | Yes | K8s API URL |
| `CLUSTER_N_TOKEN` | Yes | SA token (cluster-reader) |
| `CLUSTER_N_INCLUDE_NS` | No | Namespace include patterns (default: `*`) |
| `CLUSTER_N_EXCLUDE_NS` | No | Namespace exclude patterns (default: `openshift-*,kube-*`) |
| `THANOS_URL` | No | Prometheus/Thanos for GPU metrics |

## Tests

203 tests across 28 files. Run: `cd backend && python -m pytest app/tests/ -q`

## Key Files

```
backend/app/main.py                       — app startup, DB init, live monitoring
backend/app/db.py                         — async PostgreSQL, write queue, retention
backend/app/session/streaming_session.py  — live pipeline (watch → filter → correlate → infer)
backend/app/session/cluster_profile.py    — per-cluster adaptive thresholds
backend/app/session/signal_store.py       — in-memory store (signals, decisions, findings)
backend/app/collectors/openshift.py       — K8s watch collector (read-only, dedup, infra counts)
backend/app/nanoagents/pipeline.py        — 14-agent filter pipeline
backend/app/correlation/engine.py         — namespace + cross-cluster correlation
backend/app/inference/adapters.py         — LiteLLM client
backend/app/api/tuning.py                 — cluster profiles, EDD rubrics, proposals, clusters list
backend/app/api/workers.py                — Kafka workers + replay management
backend/app/api/incidents.py              — incident lifecycle
backend/app/analysis/evaluator.py         — EDD rubric scoring (5 dimensions)
frontend/src/App.tsx                      — routing, 3 nav groups
frontend/src/pages/Tuning.tsx             — rubrics + adaptive profiles + cluster selector + recharts
frontend/src/pages/Replay.tsx             — event replay controls + results visualization
frontend/src/pages/FleetOverview.tsx      — multi-cluster health dashboard
frontend/src/pages/Incidents.tsx          — RCA + classification + remediation
```
