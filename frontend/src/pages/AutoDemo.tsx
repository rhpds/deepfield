import { useState, useEffect } from 'react';
import type { ClusterMetrics } from '../api/client';
import FunnelChart from '../components/FunnelChart';
import PressureGauge from '../components/PressureGauge';

interface DemoState {
  status: string;
  current_step: number;
  step_count: number;
  step_progress: number;
  mode: string;
  current_step_info?: {
    id: string;
    title: string;
    subtitle: string;
    description: string;
    duration: number;
  };
  receipt?: Record<string, unknown>;
}

interface StreamState {
  metrics?: Record<string, number>;
  totals?: Record<string, number>;
  model_stats?: Record<string, { calls: number; avg_latency: number; avg_tps: number }>;
  queue_depth?: number;
  snapshots?: Array<Record<string, unknown>>;
}

const STEP_COLORS: Record<string, string> = {
  hardware: '#0071C5',
  baseline: '#3E8635',
  scale: '#F0AB00',
  stress: '#EE0000',
  recovery: '#3E8635',
  claim: '#0071C5',
};

export default function AutoDemo() {
  const [demo, setDemo] = useState<DemoState | null>(null);
  const [stream, setStream] = useState<StreamState | null>(null);
  const [cluster, setCluster] = useState<ClusterMetrics | null>(null);
  const [mode, setMode] = useState<'mock' | 'real'>('real');
  const [started, setStarted] = useState(false);

  useEffect(() => {
    const es = new EventSource('/api/v1/stream');
    es.addEventListener('demo', (e) => { try { setDemo(JSON.parse(e.data)); } catch {} });
    es.addEventListener('session', (e) => { try { const d = JSON.parse(e.data); if (d.metrics) setStream(d); } catch {} });
    es.addEventListener('cluster', (e) => { try { const d = JSON.parse(e.data); if (d.available) setCluster(d); } catch {} });
    return () => es.close();
  }, []);

  const startDemo = async () => {
    setStarted(true);
    await fetch('/api/v1/demo/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
  };

  const stopDemo = async () => {
    await fetch('/api/v1/demo/stop', { method: 'POST' });
    setStarted(false);
  };

  const step = demo?.current_step_info;
  const m = stream?.metrics;
  const cm = cluster?.models ?? {};
  const cmVals = Object.values(cm) as Array<Record<string, number | undefined>>;
  const clusterRunning = cmVals.reduce((s, v) => s + (Number(v.requests_running) || 0), 0);
  const clusterTps = cmVals.reduce((s, v) => s + (Number(v.tokens_per_sec_1m) || 0), 0);
  const stepColor = step ? STEP_COLORS[step.id] || '#6A6E73' : '#6A6E73';

  return (
    <div className="max-w-5xl mx-auto px-6 lg:px-8 py-8 space-y-6">

      {/* Not started */}
      {!started && !demo && (
        <div className="text-center py-20">
          <div className="flex justify-center items-center gap-6 mb-8">
            <img src="/logos/redhat.svg" alt="" style={{ height: '48px' }} />
            <span className="text-white text-2xl font-bold">X</span>
            <img src="/logos/intel.svg" alt="" style={{ height: '36px' }} />
          </div>
          <h1 className="text-4xl font-bold text-white mb-4" style={{ fontFamily: 'Red Hat Display' }}>
            DeepField
          </h1>
          <p className="text-lg text-[#6A6E73] max-w-2xl mx-auto mb-8">
            Fleet-scale signal intelligence for OpenShift.
            Deterministic filters compress massive telemetry so only a fraction requires expensive LLM reasoning.
          </p>
          <div className="flex items-center justify-center gap-3 mb-6">
            <div className="flex items-center gap-0.5 bg-[#252525] border border-[#333] rounded p-0.5">
              <button onClick={() => setMode('mock')} className={`px-4 py-2 rounded text-sm font-medium ${mode === 'mock' ? 'bg-[#333] text-white' : 'text-[#6A6E73]'}`}>Mock</button>
              <button onClick={() => setMode('real')} className={`px-4 py-2 rounded text-sm font-medium ${mode === 'real' ? 'text-white' : 'text-[#6A6E73]'}`}
                style={mode === 'real' ? { backgroundColor: 'var(--brand-primary)' } : {}}>Real Gaudi 3 / Xeon 6</button>
            </div>
          </div>
          <button onClick={startDemo}
            className="px-8 py-4 rounded-lg text-lg font-semibold text-white hover:opacity-90 transition"
            style={{ backgroundColor: 'var(--brand-primary)' }}>
            Run Demo
          </button>
          <p className="text-xs text-[#6A6E73] mt-4">~2 minutes • 6 automated steps • {mode === 'real' ? 'real Gaudi 3 inference' : 'mock inference'}</p>
        </div>
      )}

      {/* Step indicator */}
      {demo && demo.status === 'running' && (
        <>
          {/* Progress bar */}
          <div className="rounded-xl p-5 border border-[#333]">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                {step && <div className="w-3 h-3 rounded-full animate-pulse" style={{ backgroundColor: stepColor }} />}
                <div>
                  <h2 className="text-lg font-semibold text-white" style={{ fontFamily: 'Red Hat Display' }}>{step?.title || 'Complete'}</h2>
                  <p className="text-sm text-[#6A6E73]">{step?.subtitle || ''}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-[#6A6E73]">
                  {String(demo.status) === 'completed' ? 'Complete' : `Step ${Math.min((demo.current_step ?? 0) + 1, demo.step_count ?? 6)} of ${demo.step_count ?? 6}`}
                </span>
                {demo.status === 'running' && (
                  <button onClick={stopDemo} className="px-3 py-1.5 rounded text-xs font-medium text-white bg-red-700 hover:opacity-90">Stop</button>
                )}
                <button onClick={async () => { await fetch('/api/v1/demo/stop', { method: 'POST' }); await fetch('/api/v1/session/reset', { method: 'POST' }); setStarted(false); setDemo(null); setStream(null); setCluster(null); }}
                  className="px-3 py-1.5 rounded text-xs font-medium text-[#6A6E73] border border-[#333] hover:border-white hover:text-white">Reset</button>
              </div>
            </div>
            {/* Step progress */}
            <div className="h-1.5 bg-[#252525] rounded-full overflow-hidden mb-3">
              <div className="h-full rounded-full transition-all duration-500" style={{ width: `${demo.step_progress ?? 0}%`, backgroundColor: stepColor }} />
            </div>
            {/* Step dots */}
            <div className="flex gap-2">
              {['Hardware', 'Baseline', 'Scale', 'Stress', 'Recovery', 'Claim'].map((_, i) => (
                <div key={i} className={`flex-1 h-1 rounded ${i < (demo.current_step ?? 0) ? 'bg-[#3E8635]' : i === (demo.current_step ?? 0) ? '' : 'bg-[#333]'}`}
                  style={i === (demo.current_step ?? 0) ? { backgroundColor: stepColor } : {}} />
              ))}
            </div>
          </div>

          {/* Narration */}
          {step && (
            <div className="rounded-xl p-6 border-l-4" style={{ borderColor: stepColor, backgroundColor: '#1a1a1a' }}>
              <p className="text-sm text-[#e0e0e0] leading-relaxed">{step.description}</p>
            </div>
          )}
        </>
      )}

      {/* Live metrics during demo */}
      {m && m.raw_signals > 0 && (
        <>
          {/* Hero */}
          <div className="flex gap-4">
            <div className="flex gap-3 rounded-xl p-4 border border-[#333] items-center">
              <PressureGauge value={clusterRunning} max={50} label="Running" />
              <PressureGauge value={Math.round(clusterTps)} max={500} label="Tok/s" />
              <PressureGauge value={m.inference_in_flight ?? 0} max={20} label="In-Flight" />
            </div>
            <div className="flex-1 rounded-xl p-6 border-2 text-center" style={{ borderColor: 'var(--brand-primary)' }}>
              <div className="text-5xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>{(m.projected_clusters ?? 0).toLocaleString()}</div>
              <div className="text-sm text-[#6A6E73]">Projected Clusters Supported</div>
              <div className="text-xs text-[#6A6E73] mt-1">{m.compression_ratio}:1 compression | {m.signals_per_second} sig/s</div>
            </div>
          </div>

          {/* Key metrics */}
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
            {[
              { v: m.signals_per_second?.toFixed(0), l: 'Sig/s', c: 'text-white' },
              { v: `${m.compression_ratio}:1`, l: 'Compression', c: 'text-yellow-400' },
              { v: m.reasoning_tasks, l: 'Tasks', c: '', s: { color: 'var(--brand-primary)' } },
              { v: `${m.llm_escalation_pct}%`, l: 'Escalation', c: 'text-[#3E8635]' },
              { v: m.avg_tps?.toFixed(0), l: 'Tok/s', c: 'text-orange-400' },
              { v: `${m.avg_latency_ms?.toFixed(0)}ms`, l: 'Latency', c: '', s: { color: 'var(--brand-secondary)' } },
            ].map(({ v, l, c, s }, i) => (
              <div key={i} className="rounded-lg p-3 border border-[#333] text-center">
                <div className={`text-xl font-bold tabular-nums ${c}`} style={s}>{v}</div>
                <div className="text-[10px] text-[#6A6E73]">{l}</div>
              </div>
            ))}
          </div>

          {/* Funnel */}
          <div className="rounded-xl p-5 border border-[#333]">
            <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Signal Funnel</span>
            <div className="mt-2">
              <FunnelChart funnel={{
                raw_signals_received: m.raw_signals, normalized_signals: m.raw_signals,
                dropped_signals: m.dropped, deduped_signals: 0, suppressed_transients: 0,
                retained_signals: m.retained ?? 0, correlated_findings: m.findings ?? 0,
                reasoning_tasks_created: m.reasoning_tasks, final_insights_created: m.inference_completed ?? 0,
                signal_reduction_percent: m.raw_signals > 0 ? (m.dropped / m.raw_signals) * 100 : 0,
                llm_escalation_rate_percent: m.llm_escalation_pct, reasoning_compression_ratio: m.compression_ratio,
              }} />
            </div>
          </div>
        </>
      )}

      {/* Receipt at the end */}
      {demo?.receipt && (
        <section className="rounded-xl p-8 border-2 text-center" style={{ borderColor: 'var(--brand-primary)' }}>
          <h2 className="text-2xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>DeepField Proof</h2>
          <p className="text-[#6A6E73] mb-6">One Intel Xeon 6 / Gaudi 3 inference cluster can monitor:</p>
          <div className="text-7xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
            {Number(demo.receipt.peak_projected_clusters ?? 0).toLocaleString()}
          </div>
          <div className="text-xl text-[#6A6E73] mb-6">OpenShift Clusters</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 max-w-2xl mx-auto">
            <div><div className="text-2xl font-bold text-yellow-400">{Number(demo.receipt.max_compression_ratio ?? 0)}:1</div><div className="text-xs text-[#6A6E73]">Best Compression</div></div>
            <div><div className="text-2xl font-bold text-white">{Number(demo.receipt.total_raw_signals ?? 0).toLocaleString()}</div><div className="text-xs text-[#6A6E73]">Signals Processed</div></div>
            <div><div className="text-2xl font-bold" style={{ color: 'var(--brand-primary)' }}>{Number(demo.receipt.total_reasoning_tasks ?? 0)}</div><div className="text-xs text-[#6A6E73]">Reasoning Tasks</div></div>
            <div><div className="text-2xl font-bold text-orange-400">{Number(demo.receipt.total_inference_calls ?? 0)}</div><div className="text-xs text-[#6A6E73]">Inference Calls</div></div>
          </div>
          <div className="mt-6 text-xs text-[#6A6E73]">
            Measured on {mode === 'real' ? 'Intel Gaudi 3 + Xeon 6' : 'mock inference'} | Filter cheap. Reason expensive.
          </div>
          <button onClick={async () => { await fetch('/api/v1/session/reset', { method: 'POST' }); await fetch('/api/v1/demo/stop', { method: 'POST' }); setStarted(false); setDemo(null); setStream(null); setCluster(null); }}
            className="mt-6 px-6 py-2 rounded text-sm font-medium text-[#6A6E73] border border-[#333] hover:border-white hover:text-white">
            Reset &amp; Run Again
          </button>
        </section>
      )}

      {/* Time series during demo */}
      {stream?.snapshots && stream.snapshots.length > 2 && (
        <div className="rounded-xl p-5 border border-[#333]">
          <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Metrics Over Time</span>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-3">
            {[
              { key: 'compression_ratio', label: 'Compression', color: '#F0AB00', fmt: (v: number) => `${v}:1` },
              { key: 'projected_clusters', label: 'Clusters', color: 'var(--brand-secondary)', fmt: (v: number) => `${v}` },
              { key: 'reasoning_tasks', label: 'Tasks', color: 'var(--brand-primary)', fmt: (v: number) => `${v}` },
            ].map(({ key, label, color, fmt }) => {
              const vals = (stream.snapshots || []).slice(-20).map(s => Number((s as Record<string, unknown>)[key]) || 0);
              const max = Math.max(...vals, 1); const cur = vals[vals.length - 1] ?? 0;
              return (<div key={key}><div className="flex justify-between text-xs text-[#6A6E73] mb-1"><span>{label}</span><span style={{ color }} className="font-bold">{fmt(cur)}</span></div><div className="flex items-end gap-px h-8">{vals.map((v, i) => (<div key={i} className="flex-1 rounded-t transition-all duration-300" style={{ height: `${Math.max((v / max) * 100, 3)}%`, backgroundColor: color }} />))}</div></div>);
            })}
          </div>
        </div>
      )}
    </div>
  );
}
