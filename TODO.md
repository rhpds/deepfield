# DeepField — TODO

## What It Is

Fleet-scale OpenShift signal intelligence. Watches real clusters, compresses K8s telemetry through deterministic nano-agent filters, routes only the important signals to LLMs on Intel Gaudi 3 / Xeon 6 for root cause analysis with structured remediation. Proves one inference cluster can monitor hundreds of OpenShift clusters.

```
K8s Watch → 11 Nano Agents (deterministic) → Correlation → Micro (Xeon 6) / Macro (Gaudi 3) → RCA + Remediation → PostgreSQL
```

## Status: What Works

- [x] Live monitoring auto-starts at pod startup, watches configured clusters
- [x] Periodic re-scans every 30s + K8s watch for continuous signal flow
- [x] 11 nano-agents (PodHealth, RouteHealth, PVCHealth, NodePressure, NamespaceQuota, KServeEndpoint, KafkaLag, LaunchpadSession, TransientSuppressor, Dedupe, EventClassifier)
- [x] Correlation engine groups by namespace and cross-cluster
- [x] Structured RCA: per-signal evidence (resource names, exit codes, restart counts, owner refs, node names, event messages)
- [x] Structured JSON output (root_cause, category, evidence_chain, confidence, remediation)
- [x] Remediation suggest+confirm with click-to-execute and audit trail
- [x] All inference through LiteLLM/MAAS — no direct model endpoint calls
- [x] PostgreSQL persistence (signals, decisions, findings, inferences, remediations)
- [x] ServiceAccount token (1-year, cluster-reader) for monitoring
- [x] 6-tab UI: Demo, Simulator, Live Monitoring, Agents, LLM, Benchmarks
- [x] Repo sanitized — zero hardcoded internal URLs, tokens, or cluster names
- [x] agnosticd/agnosticv CI packaging (matches Launchpad pattern)
- [x] Apache 2.0 license
- [x] 124 tests passing
- [x] 8 chaos workload types for testing (OOM, config error, dependency fail, image pull, scheduling, storage, health check, job failure)

## TODO: Blocking Demo

- [ ] **Verify frontend live data display** — polling fallback added but never confirmed visually in browser. Hard refresh + check Live Monitoring tab.
- [ ] **Redeploy with env var config** — after sanitization, cluster configs moved to CLUSTER_1_NAME/API_URL/TOKEN env vars. Need to set these on the deployment.
- [ ] **Xeon routing proof** — LiteLLM micro models (granite-4-0-h-tiny, codellama-7b) need verification they run on Xeon CPU, not Gaudi. Alternative: get our OpenVINO models (granite-2b, phi3-mini, qwen25-3b on worker02/04/05) added to LiteLLM.

## TODO: Before Intel Summit

- [ ] **Push image to quay.io** — currently in OCP internal registry. Need `quay.io/intel-redhat/deepfield:latest` for CI.
- [ ] **Register CI in shared agnosticv repo** — `agnosticv-catalog/` and `agnosticd-config/` are ready. Ashok/Tony register in Babylon.
- [ ] **Inference cluster monitoring SA token** — need a non-expiring ServiceAccount token for read-only monitoring of the inference cluster.
- [ ] **Auto Demo page** — still uses synthetic data. Should showcase live RCA pipeline.
- [ ] **Multiple inferences per cycle** — sequential processing means one RCA per ~10-15s. Could be faster with connection management fix.
- [ ] **Re-enable OAuth/SSO** — disabled during development.

## TODO: Coordinate with Team

| Who | Task |
|-----|------|
| **Ashok** | Register agnosticv catalog entries in shared repo |
| **Ashok** | Approve read-only monitoring of rac-maas (observability, not mutation) |
| **Ashok** | Add our CPU models to LiteLLM config (granite-2b, phi3-mini, qwen25-3b) |
| **Tony** | Help with agnosticd playbook testing (devel → integration → prod) |
| **Tony** | quay.io image push setup |
| **Kersh** | Learn agnosticd/agnosticv workflow, test with `babylon deploy` |
| **Kersh** | Package demo for Intel Summit presentation narrative |

## TODO: Polish

- [ ] Historical data timeline in UI (observatory falls back to DB but no history view yet)
- [ ] Finding → inference ID linkage in database
- [ ] Session start/stop persistence
- [ ] Rate limiting on remediation execution
- [ ] Prometheus GPU utilization charts in frontend
- [ ] Signal deduplication across re-scans (dedupe agent catches some, not all)

## Architecture

| Component | Location | Tech |
|-----------|----------|------|
| Backend | Configurable cluster / `deepfield-{guid}` | Python 3.11, FastAPI, uvicorn |
| Frontend | Bundled with backend | React, TypeScript, Tailwind |
| Database | Same namespace | PostgreSQL 16, 10Gi PVC |
| Inference (GPU) | LiteLLM/MAAS | deepseek-r1-14b, phi-4, qwen3-14b on Gaudi 3 |
| Inference (CPU) | LiteLLM/MAAS | granite-4-0-h-tiny, codellama-7b on Xeon 6 |
| Monitoring | Read-only K8s Watch + Prometheus | Configurable cluster targets |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LITELLM_API_BASE` | Yes | LiteLLM proxy URL |
| `LITELLM_API_KEY` | Yes | LiteLLM API key |
| `DATABASE_URL` | No | PostgreSQL connection (works without) |
| `CLUSTER_1_NAME` | Yes | Monitored cluster name |
| `CLUSTER_1_API_URL` | Yes | K8s API URL |
| `CLUSTER_1_TOKEN` | Yes | SA token (cluster-reader) |
| `CLUSTER_1_INCLUDE_NS` | No | Namespace include patterns (default: *) |
| `CLUSTER_1_EXCLUDE_NS` | No | Namespace exclude patterns (default: openshift-*,kube-*) |
| `CLUSTER_1_ALLOW_REMEDIATION` | No | "true" to allow remediation on this cluster |
| `CLUSTER_2_*` | No | Optional second cluster |
| `THANOS_URL` | No | Prometheus/Thanos for GPU metrics |
| `SSL_VERIFY` | No | "true" for SSL verification (default: false) |

## CI Packaging

Ready at:
```
agnosticv-catalog/common.yaml    — catalog entry for Babylon
agnosticd-config/software.yml    — Ansible deployment playbook
agnosticd-config/destroy_env.yml — teardown
agnosticd-config/sample_vars.yml — example values
```

Same pattern as Launchpad and intel-rh-demo gateway.

## Tests

124 tests across 12 files. Run: `python -m pytest backend/app/tests/ -q`

## Key Files

```
backend/app/main.py                     — app startup, DB init, live monitoring
backend/app/db.py                       — async PostgreSQL, graceful degradation
backend/app/session/streaming_session.py — live pipeline (watch → filter → correlate → infer)
backend/app/inference/adapters.py       — LiteLLM client (all models)
backend/app/agents/prompts.py           — RCA/Triage/Correlation system prompts
backend/app/nanoagents/pipeline.py      — 11-agent filter pipeline
backend/app/collectors/openshift.py     — K8s watch collector (read-only)
backend/app/api/remediation.py          — suggest+confirm execution
backend/migrations/001_initial_schema.sql — 6-table PostgreSQL schema
frontend/src/pages/LiveMonitoring.tsx    — always-on cluster view
frontend/src/pages/LLMObservatory.tsx    — model fleet + inference log + remediation UI
```
