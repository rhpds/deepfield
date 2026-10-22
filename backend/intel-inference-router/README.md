# Intel CPU Inference Routing Engine

Benchmark-graded model selection, workload classification, and pressure-aware scaling for Intel Xeon CPU inference deployments.

---

## Architecture

```
                            SIGNALS (30M/day)
                                  |
                                  v
                    +----------------------------+
                    |     WorkloadBootstrapper   |
                    |  cosine similarity against |
                    |  known workload profiles   |
                    |  (sliding window, decay)   |
                    +----------------------------+
                                  |
                       workload_type + confidence
                                  |
                                  v
                    +----------------------------+
                    |      StrategyRouter        |
                    |  resolve optimization      |
                    |  flags + rubric grades     |
                    |  (INT8, cascade, batch...) |
                    +----------------------------+
                                  |
                       InferenceStrategy + flags
                                  |
                                  v
          +-----------------------------------------------+
          |              LANE ROUTER (TASK_TO_LANE)       |
          |  85% of signals are nano-rule classified      |
          |  Remaining 15% routed to five model lanes:    |
          +-----------------------------------------------+
                  |         |         |        |        |
                  v         v         v        v        v
          +---------+ +---------+ +------+ +------+ +------+
          |CLASSIFIC| |EXTRACTN | |GENERA| |REASON| |EMBED |
          |  ATION  | |         | | TION | |  ING | | DING |
          |smollm2  | |granite  | |phi3  | |qwen36| |      |
          | -360m   | | -2b    | | -mini| | -moe | |scaff-|
          |granite  | |qwen25  | |qwen25| |phi3  | | old  |
          | -350m   | | -3b   | | -3b  | | -mini| |      |
          +---------+ +---------+ +------+ +------+ +------+
              88ms      3-5s       3-8s     5-18s    <10ms
             40+tok/s                                 batch
                  |         |         |        |        |
                  +----+----+----+----+----+---+--------+
                       |              |
                       v              v
          +-------------------+  +-------------------+
          | PressureObserver  |  |   FleetManager    |
          | (Linux PSI +      |  | workload-driven   |
          |  cgroup v2)       |  | deployment plans  |
          +-------------------+  +-------------------+
                  |                       |
                  v                       v
          +-------------------+  +-------------------+
          | InferenceScaler   |  |   FleetScorecard  |
          | shed/restore by   |  | utilization,      |
          | pressure grades   |  | headroom, replicas|
          +-------------------+  +-------------------+
                  |
                  v
          +-------------------+
          |ModelLifecycleManager|
          | oc scale deploy    |
          | replicas 0..N      |
          +--------------------+
```

---

## What It Does

The router classifies incoming signals into five inference lanes, each backed by models benchmarked and graded on Intel Xeon 6 hardware (128 cores, 256 GB, AMX-INT8/AMX-BF16/AVX-512/VNNI).

### Five Lanes

| Lane            | Primary Models                         | Latency Target | Throughput  | SLA Grade |
|-----------------|----------------------------------------|----------------|-------------|-----------|
| Classification  | smollm2-360m, granite-350m             | <200ms (88ms)  | 40+ tok/s   | GREEN     |
| Extraction      | granite-2b, qwen25-3b                  | 2-5s           | --          | YELLOW    |
| Generation      | phi3-mini, qwen25-3b                   | 3-8s           | --          | YELLOW    |
| Reasoning       | qwen36-moe-35b-a3b, phi3-mini         | 5-18s          | --          | YELLOW    |
| Embedding       | scaffold (nomic-embed, all-MiniLM)     | <10ms          | batch       | --        |

Each model carries a full RubricScorecard with 10 benchmark metrics graded green/yellow/red: quality (accuracy, coherence, faithfulness), latency (TTFT, P95), throughput (tok/s, batch), variance, memory, and a composite score.

---

## Key Numbers

| Metric                    | Value          |
|---------------------------|----------------|
| Signal throughput         | 30M signals/day |
| Cascade nano-rule offload | 85% of signals |
| Classification latency    | 88ms P95       |
| Classification throughput | 200 tok/s      |
| Total memory footprint    | 38.6 GB        |
| CPU utilization           | 8% of Xeon     |
| Model roster              | 19 models      |
| Industry verticals        | 6 (FSI, healthcare, insurance, retail, telecom, basic) |
| Workload strategies       | 10 defined     |

---

## Quick Start

### Install

```bash
pip install -e ".[dev]"
```

### Compile Corpora

The routing engine needs compiled benchmark results. Point it at your benchmark output directory:

```bash
compile-corpora \
    --benchmark-dir /path/to/intel-tco-calculator/benchmarks \
    --output config/corpora.json
```

### Use in Code

```python
from intel_inference_router import (
    WorkloadBootstrapper,
    StrategyRouter,
    load_corpora,
    resolve_lane,
    resolve_lane_model,
)

# 1. Classify the workload
bootstrapper = WorkloadBootstrapper()
for signal in signal_stream:
    bootstrapper.observe(signal)

workload_type, confidence = bootstrapper.current_workload()
industry = bootstrapper.current_industry()

# 2. Resolve the inference strategy
router = StrategyRouter()
strategy = router.resolve_strategy(workload_type)

# 3. Look up the best model from compiled corpora
corpora = load_corpora()
entry = corpora.lookup(industry, task="fraud-scoring", tier="micro", strategy=strategy)

# 4. Or use lane-based routing (round-robin within lane)
lane = resolve_lane("fraud-scoring")        # -> "classification"
model = resolve_lane_model("fraud-scoring")  # -> "smollm2-360m"
```

---

## Components

### `corpora.py` -- Routing Corpora

Benchmark-graded model registry. Defines `ModelConfig`, `RubricScorecard`, `CorporaEntry`, and `RoutingCorpora`. Maps tasks to lanes (`TASK_TO_LANE`), lanes to models (`LANE_MODELS`), and models to endpoints (`CORPORA_TO_ENDPOINT`). Supports strategy-aware INT8 selection and excluded-model filtering with fallback chains.

### `strategy_router.py` -- Strategy Router

Resolves workload types to `InferenceStrategy` objects carrying optimization flags (`use_int8`, `use_cascade`, `use_speculative`, `use_batching`, `use_cache`, `use_ladder`) and expected rubric grades. Loaded from `config/strategies.yaml`.

### `bootstrapper.py` -- Workload Bootstrapper

Classifies live signal streams into workload types using cosine similarity against known workload fingerprints. Uses a sliding window (200 observations) with exponential decay weighting. Adaptive reclassification interval: aggressive (every 2) when confidence is low, conservative (every 20) when confidence is high. Produces a `ClassificationScorecard` grading confidence, reclassification speed, and namespace matching.

### `scaler.py` -- Pressure-Aware Scaler

Monitors Linux PSI (Pressure Stall Information) and cgroup v2 memory to dynamically load-shed or restore models. Evicts largest-first when pressure rises above thresholds; restores smallest-first when pressure returns to green. Hysteresis intervals (30s shed, 120s restore) prevent flapping. `PressureObserver` returns zero-pressure snapshots on non-Linux platforms for testing.

### `fleet_manager.py` -- Fleet Manager

Workload-driven deployment planner. Given a workload type and node resources, determines which models to deploy at what replica count. Allocates classification-tier models up to 8 replicas, medium-tier at 2-3, and macro-tier at 1. Produces a `FleetPlan` with a graded `FleetScorecard`.

### `models.py` -- Routing Decision Audit Trail

Immutable `RoutingDecision` records capturing full provenance: model, strategy, scorecard, serving layer, dtype, optimization, and source (corpora / fallback / explicit preference).

### `task_mapping.py` -- Task Resolution

Two-level resolution: industry-specific overrides from `verticals.yaml`, then generic shape mapping. Maps deepfield task types (e.g., `classify_signal`) to benchmark task names (e.g., `fraud-scoring`).

### `compile_corpora.py` -- Corpora Compiler

Reads benchmark results from intel-tco-calculator, ranks models by quality/latency/throughput, and writes `config/corpora.json`. Quality gate: models with red quality accuracy are excluded. Ranking priority: quality > latency > variance > throughput > smaller params.

---

## Rubric Matrix

Every metric is graded on a three-tier rubric. The overall grade is the worst of its components.

### Model Scorecard (RubricScorecard)

| Metric              | GREEN            | YELLOW            | RED              |
|---------------------|------------------|-------------------|------------------|
| Quality Accuracy    | task-specific    | task-specific     | below threshold  |
| Quality Coherence   | task-specific    | task-specific     | below threshold  |
| Quality Faithfulness| task-specific    | task-specific     | below threshold  |
| Latency TTFT        | task-specific    | task-specific     | above threshold  |
| Latency P95         | task-specific    | task-specific     | above threshold  |
| Throughput tok/s    | task-specific    | task-specific     | below threshold  |
| Throughput Batch    | task-specific    | task-specific     | below threshold  |
| Variance            | not flagged      | --                | flagged (>0.2)   |
| Memory              | within budget    | --                | over budget      |
| Composite           | derived          | derived           | derived          |

### Lane Latency Targets (ms)

| Lane            | GREEN    | YELLOW   | RED       |
|-----------------|----------|----------|-----------|
| Classification  | <=200    | <=500    | >500      |
| Extraction      | <=2000   | <=5000   | >5000     |
| Generation      | <=3000   | <=8000   | >8000     |
| Reasoning       | <=5000   | <=15000  | >15000    |
| Embedding       | <=10     | <=50     | >50       |

### Pressure Scorecard (Scaler)

| Metric                | GREEN    | YELLOW   | RED       | Direction       |
|-----------------------|----------|----------|-----------|-----------------|
| CPU some %            | <=10     | <=25     | >25       | lower is better |
| CPU full %            | <=5      | <=15     | >15       | lower is better |
| Memory some %         | <=10     | <=20     | >20       | lower is better |
| Memory used %         | <=70     | <=85     | >85       | lower is better |
| I/O some %            | <=10     | <=25     | >25       | lower is better |
| Inference budget %    | >=50     | >=25     | <25       | higher is better|
| Models available %    | >=80     | >=50     | <50       | higher is better|

**Scaler actions derived from grades:**

| Condition                  | Action          |
|----------------------------|-----------------|
| 2+ red metrics             | shed_aggressive |
| 1 red metric               | shed            |
| 1+ yellow, no red          | hold            |
| All green                  | restore         |

### Fleet Scorecard

| Metric                | GREEN    | YELLOW   | RED       |
|-----------------------|----------|----------|-----------|
| Fleet utilization %   | >=70     | >=40     | <40       |
| Replica coverage      | micro+macro | micro only | neither  |
| Memory headroom %     | >=20     | >=10     | <10       |
| Model ready %         | 100      | >=80     | <80       |
| Aggregate throughput  | >=100 tok/s | >=50 tok/s | <50 tok/s |

### Bootstrapper Scorecard

| Metric                     | GREEN    | YELLOW   | RED       |
|----------------------------|----------|----------|-----------|
| Confidence                 | >=0.8    | >=0.5    | <0.5      |
| Reclassification speed     | interval <=5 | interval >5 | --   |
| Namespace match            | matched  | --       | not matched |

---

## Testing

137 tests across 7 test modules:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=intel_inference_router

# Run a specific module
pytest tests/test_corpora.py
pytest tests/test_strategy_router.py
pytest tests/test_bootstrapper.py
pytest tests/test_scaler.py
pytest tests/test_fleet_manager.py
pytest tests/test_task_mapping.py
pytest tests/test_synthetic_routing.py
```

Test modules cover:
- **test_corpora** -- model registry, lane routing, fallback chains, INT8 selection
- **test_strategy_router** -- strategy resolution, optimization flags, YAML loading
- **test_bootstrapper** -- cosine similarity, workload classification, scorecard grading
- **test_scaler** -- pressure observation, eviction/restoration, hysteresis, budget accounting
- **test_fleet_manager** -- deployment planning, replica allocation, fleet grading
- **test_task_mapping** -- industry overrides, generic shape fallback, SLA lookup
- **test_synthetic_routing** -- end-to-end routing through the full pipeline

---

## Soak Test Results (Oberon)

Multi-hour soak test on the Oberon cluster (Intel Xeon 6, 128 cores, 256 GB) validated three capabilities:

### Model Shedding Under Pressure

When PSI metrics exceeded rubric thresholds, the scaler correctly evicted the largest models first (qwen36-moe-35b-a3b, then granite-8b variants) and restored them smallest-first once pressure returned to green. Hysteresis intervals prevented flapping during transient spikes.

### Stress Recovery

After sustained load driving CPU some% above 25 (red), the system shed models down to classification-tier only (smollm2-360m, granite-350m), maintained sub-200ms classification latency throughout, and restored the full roster within minutes of pressure relief.

### Five-Lane Routing

All five lanes operated simultaneously under mixed workload:
- Classification: 88ms P95, 200 tok/s sustained, GREEN across all rubric metrics
- Extraction: granite-2b at 3-5s, stable throughput under load
- Generation: phi3-mini at 3-8s, coherent multi-paragraph output
- Reasoning: qwen36-moe-35b-a3b at 5-18s, highest quality accuracy on complex tasks
- Embedding: scaffold layer operational for similarity search

Total memory footprint stabilized at 38.6 GB (60% of 64 GB budget), leaving 25.4 GB headroom. CPU utilization held at 8% of available Xeon cores during steady-state mixed workload.

---

## Event Flow

A signal's journey from arrival to inference result:

```
    Signal arrives
        |
        v
+------------------+
| WorkloadBoot-    |   observe(signal) -> sliding window
| strapper         |   cosine similarity vs profiles
|                  |   -> (workload_type, confidence)
+------------------+
        |
        v
+------------------+
| task_mapping     |   resolve_benchmark_task(task_type, industry)
|                  |   1. industry override (verticals.yaml)
|                  |   2. generic shape (classify_signal -> classify-short)
+------------------+
        |
        v
+------------------+
| StrategyRouter   |   resolve_strategy(workload_type)
|                  |   -> InferenceStrategy with flags:
|                  |      use_int8, use_cascade, use_batching...
+------------------+
        |
        v
+------------------+
| Lane Router      |   resolve_lane(task)
| (corpora.py)     |   -> "classification" | "extraction" | ...
|                  |   resolve_lane_model(task, excluded)
|                  |   -> "smollm2-360m" (round-robin)
+------------------+
        |
        v
+------------------+
| RoutingCorpora   |   corpora.lookup(industry, task, tier, strategy)
|                  |   -> CorporaEntry with:
|                  |      ModelConfig, RubricScorecard,
|                  |      fallback, alternatives
+------------------+
        |
        v
+------------------+
| RoutingDecision  |   Immutable audit record:
|                  |   model, strategy, scorecard, dtype,
|                  |   serving_layer, optimization, source
+------------------+
        |
        v
+------------------+
| CORPORA_TO_      |   model alias -> endpoint name
| ENDPOINT         |   "smollm2-360m" -> "smollm2_360m_cpu_xeon"
+------------------+
        |
        v
  Inference request sent to serving layer
  (OVMS / vLLM / llama-cpp)
```

---

## Configuration

### `config/strategies.yaml`

Defines 10 inference strategies mapping workload types to optimization flags and expected rubric grades. Each strategy specifies: `use_cascade`, `use_int8`, `use_speculative`, `use_batching`, `use_cache`, `use_ladder`.

Strategies: fraud-triage, dispute-resolution, loan-document-intake, compliance-screening, infrastructure-monitoring, claims-processing, retail-operations, telecom-operations, slim-classification, generic.

### `config/verticals.yaml`

Per-industry vertical definitions with latency SLAs and task overrides. Maps deepfield task types to benchmark task IDs. Defines quality gaps where no model passes the quality gate.

Industries: basic (500ms), FSI (200ms), healthcare (1000ms), insurance (2000ms), retail (500ms), telecom (500ms).

### `config/workload_profiles.yaml`

Workload fingerprints for bootstrapper classification. Each profile defines signal_type_weights, resource_kind_weights, severity_distribution, failure_class_weights, and namespace_patterns used for cosine similarity matching.

### `config/scaler.yaml`

Pressure thresholds for the rubric-graded scaler. Defines green/yellow boundaries for CPU, memory, I/O, inference budget, and model availability metrics. Also sets hysteresis intervals (30s shed, 120s restore).

### `config/corpora.json` (compiled)

Generated by `compile-corpora`. Contains the full model registry with benchmark results indexed by `[industry][task][tier]`. Not checked into source -- compiled from benchmark results.

---

## GPU Escalation (Planned)

GPU offload is designed but not yet built. Three deployment modes are planned:

| Mode        | Hardware         | Use Case                              |
|-------------|------------------|---------------------------------------|
| CPU-only    | Intel Xeon 6     | Current. 19 models, 38.6 GB, 8% CPU. Classification + extraction + generation + reasoning all on CPU with AMX acceleration. |
| CPU + GPU   | Xeon + Intel GPU | Planned. Reasoning and generation lanes escalate to GPU when CPU pressure exceeds thresholds. Classification stays on CPU. |
| GPU-primary | Intel Data Center GPU | Planned. All lanes on GPU, CPU handles only nano-rules and orchestration. |

The scaler's pressure-based eviction/restoration logic is hardware-agnostic -- the `ModelLifecycleManager` issues `oc scale` commands that work identically for CPU and GPU deployments. GPU escalation requires adding GPU pressure metrics to `PressureObserver` and GPU-aware memory estimation to `estimate_memory_gb()`.

---

## Project Structure

```
intel-inference-router/
  intel_inference_router/
    __init__.py              # Public API exports
    corpora.py               # Model registry, lane routing, rubric scorecards
    strategy_router.py       # Workload -> strategy resolution
    bootstrapper.py          # Signal classification via cosine similarity
    scaler.py                # Pressure-aware model eviction/restoration
    fleet_manager.py         # Workload-driven deployment planning
    models.py                # RoutingDecision audit trail
    task_mapping.py          # Deepfield task -> benchmark task resolution
    compile_corpora.py       # Benchmark results -> corpora.json compiler
  config/
    strategies.yaml          # Inference strategy definitions
    verticals.yaml           # Industry vertical SLAs and task overrides
    workload_profiles.yaml   # Workload fingerprints for bootstrapper
    scaler.yaml              # Pressure thresholds and hysteresis
    corpora.json             # Compiled benchmark results (generated)
  tests/
    test_corpora.py
    test_strategy_router.py
    test_bootstrapper.py
    test_scaler.py
    test_fleet_manager.py
    test_task_mapping.py
    test_synthetic_routing.py
  pyproject.toml
```

---

## License

Apache-2.0
