# Intel CPU Inference Routing Engine

Pip-installable Python package that provides benchmark-graded model selection,
workload classification, and strategy routing for Intel Xeon CPU inference
deployments.

## Architecture

```
intel_inference_router/
  corpora.py         — ModelConfig, RubricScorecard, CorporaEntry, RoutingCorpora, CORPORA_TO_ENDPOINT
  strategy_router.py — InferenceStrategy, StrategyRouter, DEFAULT_STRATEGY
  bootstrapper.py    — WorkloadBootstrapper, WorkloadProfile, WorkloadFingerprint
  task_mapping.py    — DEEPFIELD_TASK_TO_BENCHMARK_SHAPE, resolve_benchmark_task()
  compile_corpora.py — CLI compiler: benchmark results -> corpora.json
  models.py          — RoutingDecision audit trail
config/
  verticals.yaml         — 6 industry verticals with SLAs and task overrides
  strategies.yaml        — 9 rubric-graded strategies with optimization flags
  workload_profiles.yaml — 7 workload fingerprints for bootstrapper classification
```

## Key concepts

- **Corpora**: Compiled benchmark results graded against rubric thresholds (green/yellow/red).
  Each entry maps (industry, task, tier) to the best model + fallback + alternatives.
- **Strategy**: Optimization flags (use_int8, use_cascade, etc.) resolved from workload type.
- **Bootstrapper**: Classifies live signal streams into workload types using cosine similarity
  against known fingerprints. Accepts plain dicts — no deepfield imports.
- **Task mapping**: Two-level resolution from deepfield task types to benchmark shapes
  (industry override -> generic shape).

## Usage

```python
from intel_inference_router import (
    load_corpora, StrategyRouter, WorkloadBootstrapper,
    resolve_benchmark_task, RoutingDecision,
)

# Load compiled benchmark data
corpora = load_corpora()

# Resolve strategy for a workload
router = StrategyRouter()
strategy = router.resolve_strategy("fraud-triage")

# Lookup best model
task = resolve_benchmark_task("classify_signal", industry="fsi")
entry = corpora.lookup("fsi", task, tier="micro", strategy=strategy)
```

## Commands

```bash
# Install
pip install -e ".[dev]"

# Test
pytest

# Compile corpora from benchmark results
python -m intel_inference_router.compile_corpora --benchmark-dir ./benchmarks --output config/corpora.json
```

## Design decisions

- Standalone package: no imports from deepfield or any consumer
- Bootstrapper accepts dicts for signals/decisions (protocol-compatible, not type-coupled)
- Config files (YAML) live in config/ at package root, loaded by relative path
- Lazy singleton for corpora loading (load once, reload explicitly)
- 20 benchmark models across micro (<=3B) and macro (>=3.8B) tiers
