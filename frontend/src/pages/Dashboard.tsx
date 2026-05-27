import { useState, useEffect, useRef } from 'react';
import {
  api,
  type SyntheticResult,
  type BenchmarkResult,
  type BenchmarkProgress,
  type ClusterMetrics,
  type PreflightResult,
  type WarmupResult,
} from '../api/client';
import HeroMetric from '../components/HeroMetric';
import FunnelChart from '../components/FunnelChart';
import ModelTable from '../components/ModelTable';
import MetricsTimeline from '../components/MetricsTimeline';

type Phase = 'idle' | 'preflight' | 'benchmark' | 'capacity' | 'done' | 'error';

function formatTimestamp(iso: string | undefined | null): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return iso; }
}

export default function Dashboard() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState('');
  const [syntheticResult, setSyntheticResult] = useState<SyntheticResult | null>(null);
  const [benchmarkResult, setBenchmarkResult] = useState<BenchmarkResult | null>(null);
  const [benchmarkProgress, setBenchmarkProgress] = useState<BenchmarkProgress | null>(null);
  const [clusterMetrics, setClusterMetrics] = useState<ClusterMetrics | null>(null);
  const [, setProjectedClusters] = useState(0);
  const [, setCompressionRatio] = useState(0);
  const [, setP95] = useState(0);
  const [capacityDetail, setCapacityDetail] = useState<Record<string, unknown> | null>(null);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [warmup, setWarmup] = useState<WarmupResult | null>(null);
  const [preflightRunning, setPreflightRunning] = useState(false);
  const [profile, setProfile] = useState('small');
  const [seed] = useState(42);
  const [mode, setMode] = useState<'mock' | 'real'>('real');
  const [benchProfile, setBenchProfile] = useState('gaudi_blast');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const metricsRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  useEffect(() => {
    metricsRef.current = setInterval(async () => {
      try { setClusterMetrics(await api.clusterMetrics()); } catch { /* */ }
    }, 2000);
    return () => { stopPolling(); if (metricsRef.current) clearInterval(metricsRef.current); };
  }, []);

  // Step 1: Preflight
  const runPreflight = async () => {
    setPhase('preflight');
    setPreflightRunning(true);
    setPreflight(null);
    setWarmup(null);
    setError('');
    try {
      const pf = await api.preflight();
      setPreflight(pf);
      if (pf.ready) {
        const wu = await api.warmup();
        setWarmup(wu);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Preflight failed');
      setPhase('error');
    } finally {
      setPreflightRunning(false);
    }
  };

  // Step 2: Benchmark
  const runBenchmark = async () => {
    setPhase('benchmark');
    setError('');
    setBenchmarkProgress(null);
    setBenchmarkResult(null);
    try {
      const { run_id } = await api.startBenchmarkBackground(benchProfile, seed, mode);
      pollRef.current = setInterval(async () => {
        try {
          const p = await api.getBenchmarkProgress(run_id);
          setBenchmarkProgress(p);
          if (p.status === 'done' && p.final) {
            stopPolling();
            setBenchmarkResult(p.final as unknown as BenchmarkResult);
            setPhase('done');
          } else if (p.status === 'error') {
            stopPolling();
            setError('Benchmark failed');
            setPhase('error');
          }
        } catch { /* */ }
      }, 1500);
    } catch (e: unknown) {
      stopPolling();
      setError(e instanceof Error ? e.message : 'Failed');
      setPhase('error');
    }
  };

  // Step 3: Full Capacity (synthetic + benchmark + projection) — background with polling
  const [capacityPhase, setCapacityPhase] = useState('');

  const runCapacity = async () => {
    setPhase('capacity');
    setError('');
    setCapacityPhase('starting');
    setBenchmarkProgress(null);
    setCapacityDetail(null);
    setSyntheticResult(null);
    setBenchmarkResult(null);
    try {
      const { run_id } = await api.startCapacity(profile, benchProfile, seed, mode);
      pollRef.current = setInterval(async () => {
        try {
          const p = await api.getCapacityProgress(run_id);
          setCapacityPhase(p.phase);
          if (p.synthetic) setSyntheticResult(p.synthetic);
          if (p.benchmark_progress) {
            setBenchmarkProgress({
              run_id,
              profile: benchProfile,
              status: 'running',
              total: p.benchmark_progress.total,
              completed: p.benchmark_progress.completed,
              errors: p.benchmark_progress.errors,
              current_concurrency: 0,
              elapsed_ms: p.benchmark_progress.elapsed_ms,
              live_model_metrics: p.benchmark_progress.live_model_metrics,
              metrics_timeline: p.benchmark_progress.metrics_timeline,
            });
          }
          if (p.status === 'done' && p.projection) {
            stopPolling();
            if (p.benchmark) setBenchmarkResult(p.benchmark as unknown as BenchmarkResult);
            const proj = p.projection as Record<string, unknown>;
            setCapacityDetail(proj);
            setProjectedClusters(Number(proj.projected_clusters_supported ?? 0));
            setCompressionRatio(Number(proj.compression_ratio ?? 0));
            setP95(Number(proj.p95_latency_ms ?? 0));
            setBenchmarkProgress(null);
            setPhase('done');
          } else if (p.status === 'done' && !p.projection) {
            // projection not ready yet, keep polling
          } else if (p.status === 'error') {
            stopPolling();
            setError(p.error || 'Capacity run failed');
            setPhase('error');
          }
        } catch { /* ignore */ }
      }, 1500);
    } catch (e: unknown) {
      stopPolling();
      setError(e instanceof Error ? e.message : 'Failed');
      setPhase('error');
    }
  };

  const isRunning = (phase === 'preflight' && preflightRunning) || phase === 'benchmark' || phase === 'capacity';
  const preflightPassed = preflight?.ready && warmup;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">

      {/* Guided Flow */}
      <div className="rounded-xl p-5 border border-[#333]">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-sm font-semibold text-[#e0e0e0]" style={{ fontFamily: 'Red Hat Display' }}>Run Flow</span>
          <span className="text-xs text-[#6A6E73]">Preflight → Benchmark → Capacity Projection</span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {/* Step 1 */}
          <button onClick={runPreflight} disabled={isRunning}
            className={`px-4 py-2.5 rounded text-sm font-medium transition border ${
              preflightPassed ? 'border-[#3E8635] text-[#3E8635]' :
              'border-[#6A6E73] text-[#e0e0e0] hover:border-white'
            } disabled:border-gray-700 disabled:text-gray-600`}>
            {preflightRunning ? 'Checking...' : preflightPassed ? '1. Preflight ✓' : '1. Preflight Check'}
          </button>
          <span className="text-[#6A6E73]">→</span>

          {/* Step 2 */}
          <div className="flex items-center gap-2">
            <select value={benchProfile} onChange={(e) => setBenchProfile(e.target.value)}
              className="bg-[#252525] border border-[#333] rounded px-2 py-2 text-sm">
              <option value="max_throughput">max_throughput (800 reqs)</option>
              <option value="gaudi_blast">gaudi_blast (400 reqs)</option>
              <option value="full_fleet">full_fleet (100 reqs)</option>
              <option value="gaudi_race">gaudi_race (60 reqs)</option>
              <option value="model_race">model_race (50 reqs)</option>
              <option value="endpoint_sanity">endpoint_sanity (quick)</option>
            </select>
            <button onClick={runBenchmark} disabled={isRunning || !preflightPassed}
              className="px-4 py-2.5 rounded text-sm font-medium transition text-white disabled:bg-gray-700 disabled:text-gray-600 hover:opacity-90"
              style={{ backgroundColor: isRunning ? undefined : 'var(--brand-secondary)' }}>
              {phase === 'benchmark' ? 'Running...' : '2. Benchmark'}
            </button>
          </div>
          <span className="text-[#6A6E73]">→</span>

          {/* Step 3 */}
          <div className="flex items-center gap-2">
            <select value={profile} onChange={(e) => setProfile(e.target.value)}
              className="bg-[#252525] border border-[#333] rounded px-2 py-2 text-sm">
              <option value="tiny">tiny (1K signals)</option>
              <option value="small">small (10K signals)</option>
              <option value="medium">medium (50K signals)</option>
              <option value="medium_full">medium_full (250K signals)</option>
            </select>
            <button onClick={runCapacity} disabled={isRunning || !preflightPassed}
              className="px-4 py-2.5 rounded text-sm font-medium transition text-white disabled:bg-gray-700 disabled:text-gray-600 hover:opacity-90"
              style={{ backgroundColor: isRunning ? undefined : 'var(--brand-primary)' }}>
              {phase === 'capacity'
            ? capacityPhase === 'synthetic' ? '⟳ Synthetic...'
            : capacityPhase === 'benchmark' ? '⟳ Benchmarking...'
            : capacityPhase === 'projection' ? '⟳ Projecting...'
            : '⟳ Starting...'
            : '3. Capacity Projection'}
            </button>
          </div>

          {/* Mode toggle */}
          <div className="ml-auto flex items-center gap-1 bg-[#252525] border border-[#333] rounded p-0.5">
            <button onClick={() => setMode('mock')}
              className={`px-3 py-1.5 rounded text-xs font-medium transition ${mode === 'mock' ? 'bg-[#333] text-white' : 'text-[#6A6E73]'}`}>
              Mock
            </button>
            <button onClick={() => setMode('real')}
              className={`px-3 py-1.5 rounded text-xs font-medium transition ${mode === 'real' ? 'text-white' : 'text-[#6A6E73]'}`}
              style={mode === 'real' ? { backgroundColor: 'var(--brand-primary)' } : {}}>
              Real
            </button>
          </div>
        </div>
      </div>

      {error && <div className="bg-red-900/30 border border-red-800 text-red-300 px-4 py-3 rounded text-sm">{error}</div>}

      {/* Capacity Progress */}
      {phase === 'capacity' && (
        <section className="rounded-xl p-5 border border-[#333]">
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full animate-pulse" style={{ backgroundColor: 'var(--brand-primary)' }} />
            <span className="text-sm font-medium text-[#e0e0e0]">
              {capacityPhase === 'synthetic' && 'Processing synthetic fleet signals through nano-agent pipeline...'}
              {capacityPhase === 'benchmark' && 'Running inference benchmark against Gaudi 3 / Xeon 6...'}
              {capacityPhase === 'projection' && 'Computing capacity projection...'}
              {capacityPhase === 'starting' && 'Starting capacity run...'}
            </span>
          </div>
        </section>
      )}

      {/* Preflight Results */}
      {preflight && (
        <section className={`rounded-xl p-5 border ${preflight.ready ? 'border-[#3E8635]/40' : 'border-red-800/40'}`}>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">Preflight</h2>
            <span className={`text-xs font-bold ${preflight.ready ? 'text-[#3E8635]' : 'text-red-400'}`}>
              {preflight.ready ? 'READY' : 'NOT READY'} — {preflight.reachable_count}/{preflight.total_count} endpoints
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {Object.entries(preflight.models).map(([key, m]) => (
              <div key={key} className={`bg-[#252525] rounded p-2.5 border-l-2 ${m.reachable ? 'border-[#3E8635]' : 'border-red-500'}`}>
                <div className="text-xs font-mono text-[#6A6E73] truncate">{key.split('_').slice(0, 2).join('_')}</div>
                <div className={`text-[10px] font-semibold ${m.hardware_lane === 'gaudi3' ? 'text-orange-400' : 'text-[#0071C5]'}`}>{m.hardware_lane}</div>
                {m.reachable && <div className="text-xs text-[#3E8635]">{m.latency_ms}ms</div>}
                {warmup?.models[key] && (
                  <div className="text-[10px] text-[#6A6E73] mt-0.5">
                    warm: {warmup.models[key].latency_ms.toFixed(0)}ms / {warmup.models[key].tokens_out}tok
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Hero Capacity Projection */}
      {(() => {
        const pcs = capacityDetail && (capacityDetail as any).projected_clusters_supported;
        if (pcs === undefined || pcs === null) return null;
        return (
        <section className="rounded-xl p-8 border-2" style={{ borderColor: 'var(--brand-primary)' }}>
          <div className="text-center mb-6">
            <div className="text-6xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
              {pcs}
            </div>
            <div className="text-lg text-[#6A6E73]">Projected OpenShift Clusters Supported</div>
            <div className="text-xs text-[#6A6E73] mt-1">
              by one Intel Xeon 6 / Gaudi 3 inference cluster at p95 &lt; {Number((capacityDetail as any).p95_latency_ms || 0).toFixed(0)}ms
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <HeroMetric
              value={Number((capacityDetail as any).compression_ratio).toFixed(1) + ':1'}
              label="Compression Ratio" color="text-yellow-400" />
            <HeroMetric
              value={Number((capacityDetail as any).total_rps_all_models || 0).toFixed(1)}
              label="Combined RPS" color="text-[#0071C5]" />
            <HeroMetric
              value={Number((capacityDetail as any).max_reasoning_tasks_per_minute || 0).toFixed(0)}
              label="Reasoning/min" color="text-orange-400" />
            <HeroMetric
              value={(capacityDetail as any).benchmark_mode === 'real' ? 'REAL' : 'MOCK'}
              label="Hardware Mode"
              color={(capacityDetail as any).benchmark_mode === 'real' ? 'text-[#3E8635]' : 'text-[#6A6E73]'} />
          </div>
          {(capacityDetail as any).model_breakdown && (
            <div className="mt-6 pt-4 border-t border-[#333]">
              <h3 className="text-xs text-[#6A6E73] mb-3 uppercase tracking-wide">Per-Model Contribution</h3>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {Object.entries((capacityDetail as any).model_breakdown as Record<string, any>).map(([model, m]) => (
                  <div key={model} className="bg-[#252525] rounded p-3">
                    <div className="text-xs font-mono text-[#6A6E73] truncate">{model.split('_').slice(0, 2).join('_')}</div>
                    <div className={`text-[10px] font-semibold ${m.hardware === 'gaudi3' ? 'text-orange-400' : 'text-[#0071C5]'}`}>{m.hardware}</div>
                    <div className="text-lg font-bold text-white mt-1">{m.rps} <span className="text-[10px] text-[#6A6E73]">RPS</span></div>
                    <div className="text-xs text-[#6A6E73]">{m.tok_s?.toFixed(0)} tok/s | {m.p95_ms?.toFixed(0)}ms</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
        );
      })()}

      {/* Live Benchmark Progress */}
      {benchmarkProgress && (benchmarkProgress.status === 'running' || phase === 'capacity') && benchmarkProgress.completed > 0 && (
        <section className="rounded-xl p-5 border border-[#333]">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">Live Benchmark</h2>
            <div className="flex items-center gap-3 text-xs">
              <span style={{ color: 'var(--brand-primary)' }} className="animate-pulse font-bold">RUNNING</span>
              <span className="text-[#6A6E73]">c={benchmarkProgress.current_concurrency}</span>
              <span className="text-[#6A6E73]">{(benchmarkProgress.elapsed_ms / 1000).toFixed(1)}s</span>
              {(benchmarkProgress as any).started_at && (
                <span className="text-[#6A6E73]">{formatTimestamp((benchmarkProgress as any).started_at)}</span>
              )}
            </div>
          </div>
          <div className="h-2 bg-[#252525] rounded-full overflow-hidden mb-3">
            <div className="h-full rounded-full transition-all duration-300"
              style={{ width: `${benchmarkProgress.total ? (benchmarkProgress.completed / benchmarkProgress.total) * 100 : 0}%`, backgroundColor: 'var(--brand-secondary)' }} />
          </div>
          <div className="flex justify-between text-xs text-[#6A6E73] mb-3">
            <span>{benchmarkProgress.completed} / {benchmarkProgress.total}</span>
            <span>{benchmarkProgress.errors > 0 ? `${benchmarkProgress.errors} errors` : 'no errors'}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {Object.entries(benchmarkProgress.live_model_metrics).map(([model, m]) => (
              <div key={model} className="bg-[#252525] rounded p-3">
                <div className="text-xs font-mono text-[#6A6E73] truncate">{model.split('_').slice(0, 2).join('_')}</div>
                <div className={`text-[10px] font-semibold ${m.hardware_lane === 'gaudi3' ? 'text-orange-400' : 'text-[#0071C5]'}`}>{m.hardware_lane}</div>
                <div className="text-xl font-bold text-white tabular-nums">{m.avg_tps.toFixed(0)} <span className="text-[10px] text-[#6A6E73]">tok/s</span></div>
                <div className="text-xs text-[#6A6E73] tabular-nums">{m.avg_latency_ms.toFixed(0)}ms | {m.completed} done</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Cluster Hardware (Live) */}
      {clusterMetrics && clusterMetrics.available && (
        <section className="rounded-xl p-5 border border-[#333]">
          <h2 className="text-sm font-semibold mb-3">Cluster Hardware (Live from Prometheus)</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {Object.entries(clusterMetrics.models).map(([model, m]) => (
              <div key={model} className="bg-[#252525] rounded p-3">
                <div className="text-xs font-mono text-[#6A6E73] truncate">{model}</div>
                <div className="mt-1 space-y-0.5 text-xs">
                  {m.requests_running !== undefined && (
                    <div className="flex justify-between">
                      <span className="text-[#6A6E73]">Running</span>
                      <span className={`font-bold ${(m.requests_running ?? 0) > 0 ? 'text-[#3E8635]' : 'text-[#333]'}`}>{m.requests_running}</span>
                    </div>
                  )}
                  {m.kv_cache_pct !== undefined && (
                    <div className="flex justify-between">
                      <span className="text-[#6A6E73]">KV Cache</span>
                      <span className="font-bold text-white">{m.kv_cache_pct}%</span>
                    </div>
                  )}
                  {m.tokens_per_sec_1m !== undefined && m.tokens_per_sec_1m > 0 && (
                    <div className="flex justify-between">
                      <span className="text-[#6A6E73]">Tok/s</span>
                      <span className="font-bold text-orange-400">{m.tokens_per_sec_1m}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Metrics Timeline */}
      {benchmarkProgress?.metrics_timeline && benchmarkProgress.metrics_timeline.length > 0 && (
        <MetricsTimeline timeline={benchmarkProgress.metrics_timeline} />
      )}

      {/* Signal Funnel */}
      {syntheticResult && (
        <section className="rounded-xl p-5 border border-[#333]">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">Signal Funnel</h2>
            {(syntheticResult as any).started_at && (
              <span className="text-xs text-[#6A6E73]">{formatTimestamp((syntheticResult as any).started_at)}</span>
            )}
          </div>
          <FunnelChart funnel={syntheticResult.funnel} />
          <div className="mt-3 grid grid-cols-3 gap-4 text-center text-xs text-[#6A6E73]">
            <div><div className="text-base text-white font-semibold">{syntheticResult.funnel.signal_reduction_percent.toFixed(1)}%</div>Filtered</div>
            <div><div className="text-base text-white font-semibold">{syntheticResult.funnel.llm_escalation_rate_percent.toFixed(4)}%</div>LLM Escalation</div>
            <div><div className="text-base text-white font-semibold">{syntheticResult.duration_ms.toFixed(0)}ms</div>Duration</div>
          </div>
        </section>
      )}

      {/* Benchmark Results */}
      {benchmarkResult && (
        <section className="rounded-xl p-5 border border-[#333]">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">Benchmark: {benchmarkResult.profile}</h2>
            <span className="text-xs text-[#6A6E73]">
              {benchmarkResult.total_requests} reqs | {benchmarkResult.duration_ms.toFixed(0)}ms | {benchmarkResult.mode ?? mode}
              {(benchmarkResult as any).started_at && <> | {formatTimestamp((benchmarkResult as any).started_at)}</>}
            </span>
          </div>
          <ModelTable metrics={benchmarkResult.model_metrics} />
        </section>
      )}

      {/* Idle State */}
      {phase === 'idle' && (
        <div className="text-center py-16">
          <div className="flex justify-center items-center gap-6 mb-6">
            <img src="/logos/redhat.svg" alt="" style={{ height: '36px', opacity: 0.3 }} />
            <span className="text-[#6A6E73] text-xl font-bold">X</span>
            <img src="/logos/intel.svg" alt="" style={{ height: '28px', opacity: 0.3 }} />
          </div>
          <p className="text-xl mb-2 text-[#e0e0e0]" style={{ fontFamily: 'Red Hat Display' }}>
            Filter cheap. Reason expensive.
          </p>
          <p className="text-sm text-[#6A6E73] max-w-md mx-auto">
            Start with Preflight Check, then run a Benchmark, then compute Capacity Projection.
          </p>
        </div>
      )}
    </div>
  );
}
