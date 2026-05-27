const BASE = '';

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  health: () => get<{ status: string }>('/health'),
  runSynthetic: (profile = 'tiny', seed = 42, mode = 'mock') =>
    post<SyntheticResult>('/api/v1/runs/synthetic', { profile, seed, mode }),
  runBenchmark: (profile = 'model_race', seed = 42, mode = 'mock') =>
    post<BenchmarkResult>('/api/v1/runs/benchmark', { profile, seed, mode }),
  startBenchmarkBackground: (profile = 'model_race', seed = 42, mode = 'mock') =>
    post<{ run_id: string; status: string }>('/api/v1/runs/benchmark', { profile, seed, mode, background: true }),
  getBenchmarkProgress: (runId: string) =>
    get<BenchmarkProgress>(`/api/v1/runs/benchmark/status/${runId}`),
  startCapacity: (syntheticProfile = 'small', benchmarkProfile = 'model_race', seed = 42, mode = 'mock') =>
    post<{ run_id: string; status: string }>('/api/v1/runs/capacity', {
      synthetic_profile: syntheticProfile,
      benchmark_profile: benchmarkProfile,
      seed,
      mode,
    }),
  getCapacityProgress: (runId: string) =>
    get<CapacityProgress>(`/api/v1/runs/capacity/status/${runId}`),
  preflight: () => post<PreflightResult>('/api/v1/preflight', {}),
  warmup: () => post<WarmupResult>('/api/v1/warmup', {}),
  clusterMetrics: () => get<ClusterMetrics>('/api/v1/cluster/metrics'),
  listRuns: () => get<{ runs: SyntheticResult[]; benchmarks: BenchmarkResult[] }>('/api/v1/runs'),
};

export interface BenchmarkProgress {
  run_id: string;
  profile: string;
  status: 'starting' | 'running' | 'done' | 'error';
  total: number;
  completed: number;
  errors: number;
  current_concurrency: number;
  elapsed_ms: number;
  live_model_metrics: Record<string, {
    hardware_lane: string;
    completed: number;
    errors: number;
    avg_latency_ms: number;
    avg_tps: number;
  }>;
  metrics_timeline?: MetricsSnapshot[];
  final?: BenchmarkResult;
}

export interface MetricsSnapshot {
  t_ms: number;
  completed: number;
  concurrency: number;
  models: Record<string, {
    requests_running?: number;
    requests_waiting?: number;
    kv_cache_pct?: number;
    tokens_per_sec_1m?: number;
    rps_1m?: number;
  }>;
}

export interface ClusterMetrics {
  available: boolean;
  models: Record<string, {
    requests_running?: number;
    requests_waiting?: number;
    kv_cache_pct?: number;
    gpu_cache_pct?: number;
    tokens_per_sec_1m?: number;
    rps_1m?: number;
  }>;
  nodes: Record<string, { cpu_pct: number }>;
}

export interface SignalFunnel {
  raw_signals_received: number;
  normalized_signals: number;
  dropped_signals: number;
  deduped_signals: number;
  suppressed_transients: number;
  retained_signals: number;
  correlated_findings: number;
  reasoning_tasks_created: number;
  final_insights_created: number;
  signal_reduction_percent: number;
  llm_escalation_rate_percent: number;
  reasoning_compression_ratio: number;
}

export interface SyntheticResult {
  run_id: string;
  mode: string;
  profile: string;
  seed: number;
  duration_ms: number;
  clusters: number;
  raw_signals: number;
  normalized: number;
  pipeline: { suppressed: number; deduped: number; escalated: number; remaining: number };
  routing: { kept: number; dropped: number };
  findings: number;
  reasoning_tasks: number;
  inference_results: { task_id: string; model: string; route: string; latency_ms: number; tokens_out: number }[];
  funnel: SignalFunnel;
  avg_signals_per_cluster: number;
}

export interface ModelMetrics {
  model_name: string;
  hardware_lane: string;
  concurrency_level: number;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  tokens_per_second: number;
  requests_per_second: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  error_rate: number;
  stable: boolean;
}

export interface BenchmarkResult {
  benchmark_run_id: string;
  profile: string;
  total_requests: number;
  duration_ms: number;
  model_metrics: Record<string, ModelMetrics>;
  saturation: Record<string, { max_stable_concurrency: number; max_stable_rps: number }>;
  mode: string;
}

export interface CapacityResult {
  synthetic: SyntheticResult;
  benchmark: BenchmarkResult;
  projection: {
    projection: {
      reasoning_compression_ratio: number;
      max_reasoning_tasks_per_minute: number;
      max_raw_signals_per_minute: number;
      avg_raw_signals_per_cluster_per_minute: number;
      projected_clusters_supported: number;
      p95_latency_ms: number;
    };
    projected_clusters_supported: number;
    compression_ratio: number;
  };
}

export interface CapacityProgress {
  run_id: string;
  status: 'running' | 'done' | 'error';
  phase: 'starting' | 'synthetic' | 'benchmark' | 'projection' | 'done';
  synthetic?: SyntheticResult;
  benchmark_progress?: {
    completed: number;
    total: number;
    errors: number;
    elapsed_ms: number;
    live_model_metrics: Record<string, { hardware_lane: string; completed: number; errors: number; avg_latency_ms: number; avg_tps: number }>;
    metrics_timeline?: MetricsSnapshot[];
  };
  projection?: Record<string, unknown>;
  benchmark?: BenchmarkResult;
  error?: string;
}

export interface PreflightResult {
  status: 'running' | 'passed' | 'failed';
  token_valid: boolean;
  prometheus_connected: boolean;
  reachable_count: number;
  total_count: number;
  ready: boolean;
  warnings: string[];
  models: Record<string, {
    url: string;
    model_name: string;
    hardware_lane: string;
    reachable: boolean;
    latency_ms: number;
    error: string | null;
  }>;
}

export interface WarmupResult {
  total_ms: number;
  models: Record<string, {
    status: 'ok' | 'error' | 'pending';
    latency_ms: number;
    tokens_out: number;
    error: string | null;
  }>;
}
