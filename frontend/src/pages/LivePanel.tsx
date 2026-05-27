import { useState, useEffect } from 'react';
import type { ClusterMetrics } from '../api/client';
import FunnelChart from '../components/FunnelChart';
import PressureGauge from '../components/PressureGauge';

interface StreamState {
  session_id: string;
  status: string;
  mode: string;
  params: { clusters: number; failure_rate: number; signals_per_second: number; concurrency: number; models_enabled: Record<string, boolean> };
  metrics: Record<string, number>;
  totals: Record<string, number>;
  model_stats: Record<string, { calls: number; avg_latency: number; avg_tps: number }>;
  live_inference: { last_model?: string; last_latency_ms?: number; in_flight?: number; completed?: number };
  snapshots: Array<Record<string, unknown>>;
  queue_depth: number;
}

const MODEL_LABELS: Record<string, { short: string; hw: string; tier: string }> = {
  // Macro agents — Gaudi 3 GPU
  deepseek_r1_distill_qwen_14b_gaudi: { short: 'DeepSeek R1', hw: 'Gaudi 3', tier: 'macro' },
  phi4_gaudi: { short: 'Phi-4', hw: 'Gaudi 3', tier: 'macro' },
  qwen3_14b_gaudi_a: { short: 'Qwen3 (A)', hw: 'Gaudi 3', tier: 'macro' },
  qwen3_14b_gaudi_b: { short: 'Qwen3 (B)', hw: 'Gaudi 3', tier: 'macro' },
  // Micro agents — Xeon 6 CPU (OpenVINO)
  granite_2b_cpu_xeon: { short: 'Granite 2B', hw: 'Xeon 6', tier: 'micro' },
  phi3_mini_cpu_xeon: { short: 'Phi-3 mini', hw: 'Xeon 6', tier: 'micro' },
  qwen25_3b_cpu_xeon: { short: 'Qwen 2.5 3B', hw: 'Xeon 6', tier: 'micro' },
  // Legacy
  llama_3_1_70b_q4_xeon: { short: 'Llama 70B', hw: 'Xeon 6', tier: 'legacy' },
};

export default function LivePanel() {
  const [state, setState] = useState<StreamState | null>(null);
  const [clusterMetrics, setClusterMetrics] = useState<ClusterMetrics | null>(null);
  const [running, setRunning] = useState(false);
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);
  const [mode, setMode] = useState<'mock' | 'real'>('real');
  const [clusters, setClusters] = useState(5);
  const [failureRate, setFailureRate] = useState(2);
  const [signalsPerSec, setSignalsPerSec] = useState(100);
  const [routingMode, setRoutingMode] = useState<'production' | 'demo'>('production');
  const [modelsEnabled, setModelsEnabled] = useState<Record<string, boolean>>({
    // Macro (Gaudi 3)
    deepseek_r1_distill_qwen_14b_gaudi: true,
    phi4_gaudi: true,
    qwen3_14b_gaudi_a: true,
    qwen3_14b_gaudi_b: true,
    // Micro (Xeon 6)
    granite_2b_cpu_xeon: true,
    phi3_mini_cpu_xeon: true,
    qwen25_3b_cpu_xeon: true,
    // Legacy
    llama_3_1_70b_q4_xeon: false,
  });

  useEffect(() => {
    const es = new EventSource('/api/v1/stream');
    es.addEventListener('session', (e) => { try { const d = JSON.parse(e.data); if (d.session_id) setState(d); } catch {} });
    es.addEventListener('cluster', (e) => { try { const d = JSON.parse(e.data); if (d.available) setClusterMetrics(d); } catch {} });
    return () => es.close();
  }, []);

  const startSession = async () => { setRunning(true); setReceipt(null); await fetch('/api/v1/session/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, source: 'synthetic', clusters, failure_rate: failureRate / 100, signals_per_second: signalsPerSec, routing_mode: routingMode }) }); };
  const stopSession = async () => { const r = await fetch('/api/v1/session/stop', { method: 'POST' }); const d = await r.json(); if (d.receipt) setReceipt(d.receipt); setRunning(false); };
  const resetSession = async () => { await fetch('/api/v1/session/reset', { method: 'POST' }); setState(null); setReceipt(null); setRunning(false); };
  const updateParam = async (k: string, v: unknown) => { await fetch('/api/v1/session/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [k]: v }) }); };
  const toggleModel = async (model: string) => { const u = { ...modelsEnabled, [model]: !modelsEnabled[model] }; setModelsEnabled(u); await updateParam('models_enabled', u); };

  const m = state?.metrics;
  const t = state?.totals;
  const snaps = state?.snapshots || [];
  const li = state?.live_inference;
  const cm = clusterMetrics?.models ?? {};
  const cmVals = Object.values(cm) as Array<Record<string, number | undefined>>;
  const clusterRunning = cmVals.reduce((s, v) => s + (Number(v.requests_running) || 0), 0);
  const clusterQueued = cmVals.reduce((s, v) => s + (Number(v.requests_waiting) || 0), 0);
  const clusterTps = cmVals.reduce((s, v) => s + (Number(v.tokens_per_sec_1m) || 0), 0);
  const pressureScore = Math.min(100, Math.round(clusterRunning * 2 * 0.4 + clusterQueued * 5 * 0.35));

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-5">
      {/* Controls */}
      <div className="rounded-xl p-5 border border-[#333]">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold" style={{ fontFamily: 'Red Hat Display' }}>Live Control Panel — Streaming</h2>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-0.5 bg-[#252525] border border-[#333] rounded p-0.5">
              <button onClick={() => setMode('mock')} className={`px-3 py-1 rounded text-xs font-medium ${mode === 'mock' ? 'bg-[#333] text-white' : 'text-[#6A6E73]'}`}>Mock</button>
              <button onClick={() => setMode('real')} className={`px-3 py-1 rounded text-xs font-medium ${mode === 'real' ? 'text-white' : 'text-[#6A6E73]'}`} style={mode === 'real' ? { backgroundColor: 'var(--brand-primary)' } : {}}>Real</button>
            </div>
            <div className="flex items-center gap-0.5 bg-[#252525] border border-[#333] rounded p-0.5">
              <button onClick={() => setRoutingMode('production')} className={`px-3 py-1 rounded text-xs font-medium ${routingMode === 'production' ? 'bg-[#333] text-white' : 'text-[#6A6E73]'}`}>Production</button>
              <button onClick={() => setRoutingMode('demo')} className={`px-3 py-1 rounded text-xs font-medium ${routingMode === 'demo' ? 'text-white' : 'text-[#6A6E73]'}`}
                style={routingMode === 'demo' ? { backgroundColor: '#F0AB00' } : {}}>Demo (distribute)</button>
            </div>
            {!running ? (<>
              <button onClick={startSession} className="px-4 py-2 rounded text-sm font-medium text-white hover:opacity-90" style={{ backgroundColor: 'var(--brand-green)' }}>Start</button>
              {(state || receipt) && <button onClick={resetSession} className="px-3 py-2 rounded text-sm font-medium text-[#6A6E73] border border-[#333] hover:border-white hover:text-white">Reset</button>}
            </>) : (
              <button onClick={stopSession} className="px-4 py-2 rounded text-sm font-medium text-white hover:opacity-90 bg-red-700">Stop</button>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div><label className="text-xs text-[#6A6E73] block mb-1">Fleet Scale</label><input type="range" min="1" max="100" value={clusters} onChange={(e) => { setClusters(Number(e.target.value)); if (running) updateParam('clusters', Number(e.target.value)); }} className="w-full accent-[#0071C5]" /><div className="text-lg font-bold text-white text-center">{clusters} clusters</div></div>
          <div><label className="text-xs text-[#6A6E73] block mb-1">Failure Rate</label><input type="range" min="1" max="30" value={failureRate} onChange={(e) => { setFailureRate(Number(e.target.value)); if (running) updateParam('failure_rate', Number(e.target.value) / 100); }} className="w-full accent-[#EE0000]" /><div className="text-lg font-bold text-white text-center">{failureRate}%</div></div>
          <div><label className="text-xs text-[#6A6E73] block mb-1">Signals/sec</label><input type="range" min="10" max="1000" step="10" value={signalsPerSec} onChange={(e) => { setSignalsPerSec(Number(e.target.value)); if (running) updateParam('signals_per_second', Number(e.target.value)); }} className="w-full accent-[#F0AB00]" /><div className="text-lg font-bold text-white text-center">{signalsPerSec}/s</div></div>
          <div><label className="text-xs text-[#6A6E73] block mb-1">Models</label><div className="space-y-0.5"><div className="text-[9px] text-[#6A6E73] uppercase mb-0.5">Macro (Gaudi 3)</div>{Object.entries(MODEL_LABELS).filter(([,v]) => v.tier === 'macro').map(([key, { short }]) => (<label key={key} className="flex items-center gap-2 text-xs cursor-pointer"><input type="checkbox" checked={modelsEnabled[key]} onChange={() => toggleModel(key)} className="accent-orange-400" /><span className={modelsEnabled[key] ? 'text-white' : 'text-[#6A6E73]'}>{short}</span><span className="text-[10px] text-orange-400">▲</span></label>))}<div className="text-[9px] text-[#6A6E73] uppercase mt-1 mb-0.5">Micro (Xeon 6)</div>{Object.entries(MODEL_LABELS).filter(([,v]) => v.tier === 'micro').map(([key, { short }]) => (<label key={key} className="flex items-center gap-2 text-xs cursor-pointer"><input type="checkbox" checked={modelsEnabled[key]} onChange={() => toggleModel(key)} className="accent-[#0071C5]" /><span className={modelsEnabled[key] ? 'text-white' : 'text-[#6A6E73]'}>{short}</span><span className="text-[10px] text-[#0071C5]">▼</span></label>))}</div></div>
          <div><label className="text-xs text-[#6A6E73] block mb-1">Queue</label><div className="text-3xl font-bold text-white text-center tabular-nums">{state?.queue_depth ?? 0}</div><div className="text-[10px] text-[#6A6E73] text-center">buffered</div>{li?.last_model && <div className="text-[10px] text-orange-400 text-center mt-1 font-mono truncate">{li.last_model.split('_').slice(0,2).join('_')} → {li.last_latency_ms}ms</div>}</div>
        </div>
      </div>

      {running && !m?.raw_signals && (<div className="rounded-xl p-6 border border-[#333] text-center"><div className="w-3 h-3 rounded-full animate-pulse mx-auto mb-3" style={{ backgroundColor: 'var(--brand-primary)' }} /><div className="text-lg text-[#e0e0e0]">Starting stream...</div><div className="text-sm text-[#6A6E73] mt-1">Signals flowing at {signalsPerSec}/s</div></div>)}

      {m && m.raw_signals > 0 && (<div className="flex gap-4">
        <div className="flex gap-3 rounded-xl p-4 border border-[#333] items-center">
          <PressureGauge value={pressureScore} max={100} label="System" />
          <PressureGauge value={clusterRunning} max={50} label="Running" />
          <PressureGauge value={clusterQueued} max={20} label="Queued" />
          <PressureGauge value={Math.round(clusterTps)} max={500} label="Tok/s" />
          <PressureGauge value={m.inference_in_flight ?? 0} max={20} label="In-Flight" />
        </div>
        <div className="flex-1 rounded-xl p-6 border-2 text-center" style={{ borderColor: 'var(--brand-primary)' }}>
          <div className="text-5xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>{(m.projected_clusters ?? 0).toLocaleString()}</div>
          <div className="text-sm text-[#6A6E73]">Projected Clusters Supported</div>
          <div className="text-xs text-[#6A6E73] mt-1">{m.compression_ratio}:1 | {m.signals_per_second} sig/s</div>
        </div>
      </div>)}

      {m && m.raw_signals > 0 && (<><div className="grid grid-cols-3 md:grid-cols-7 gap-2">
        {[{ v: m.signals_per_second?.toFixed(0), l: 'Sig/s', c: 'text-white' },{ v: `${m.compression_ratio}:1`, l: 'Compression', c: 'text-yellow-400' },{ v: m.reasoning_tasks, l: 'Tasks', c: '', s: { color: 'var(--brand-primary)' } },{ v: `${m.llm_escalation_pct}%`, l: 'Escalation', c: 'text-[#3E8635]' },{ v: m.avg_tps?.toFixed(0), l: 'Tok/s', c: 'text-orange-400' },{ v: `${m.avg_latency_ms?.toFixed(0)}ms`, l: 'Latency', c: '', s: { color: 'var(--brand-secondary)' } },{ v: m.inference_in_flight, l: 'In-Flight', c: 'text-orange-400' }].map(({ v, l, c, s }, i) => (
          <div key={i} className="rounded-lg p-2 border border-[#333] text-center"><div className={`text-lg font-bold tabular-nums ${c}`} style={s}>{v}</div><div className="text-[10px] text-[#6A6E73]">{l}</div></div>
        ))}
      </div>
      {t && (<div className="rounded-lg p-3 border border-[#333] flex flex-wrap items-center justify-between gap-3">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Totals</span>
        <div className="flex flex-wrap gap-4 text-xs tabular-nums">
          <span><span className="text-[#6A6E73]">Signals:</span> <span className="text-white font-bold">{(t.raw_signals ?? 0).toLocaleString()}</span></span>
          <span><span className="text-[#6A6E73]">Tasks:</span> <span className="font-bold" style={{ color: 'var(--brand-primary)' }}>{(t.reasoning_tasks ?? 0).toLocaleString()}</span></span>
          <span><span className="text-[#6A6E73]">Comp:</span> <span className="text-yellow-400 font-bold">{t.cumulative_compression_ratio ?? 0}:1</span></span>
          <span><span className="text-[#6A6E73]">Inference:</span> <span className="text-orange-400 font-bold">{(t.inference_calls ?? 0).toLocaleString()}</span></span>
        </div>
      </div>)}</>)}

      {state?.model_stats && Object.keys(state.model_stats).length > 0 && (<div className="rounded-xl p-4 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Model Performance</span>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">{Object.entries(state.model_stats).map(([model, stats]) => (
          <div key={model} className="bg-[#1a1a1a] rounded p-2 border-l-2 border-[#3E8635]"><div className="text-[10px] font-mono text-[#6A6E73] truncate">{model.split('_').slice(0,2).join('_')}</div><div className="text-lg font-bold text-white mt-1">{stats.calls} <span className="text-[10px] text-[#6A6E73]">calls</span></div><div className="text-xs text-orange-400">{stats.avg_tps} tok/s | {stats.avg_latency}ms</div></div>
        ))}</div>
      </div>)}

      {clusterMetrics?.available && (<div className="rounded-xl p-4 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Cluster Pressure</span>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">{Object.entries(cm).map(([model, mv]) => { const v = mv as Record<string, number | undefined>; return (
          <div key={model} className={`bg-[#1a1a1a] rounded p-2 border-l-2 ${(Number(v.requests_running) || 0) > 0 ? 'border-[#3E8635]' : 'border-[#333]'}`}><div className="text-[10px] font-mono text-[#6A6E73] truncate">{model}</div><div className="flex gap-2 mt-1 text-xs tabular-nums"><span className={(Number(v.requests_running) || 0) > 0 ? 'text-[#3E8635] font-bold' : 'text-[#333]'}>{v.requests_running ?? 0}r</span><span className={(Number(v.requests_waiting) || 0) > 0 ? 'text-yellow-400' : 'text-[#333]'}>{v.requests_waiting ?? 0}q</span>{(Number(v.tokens_per_sec_1m) || 0) > 0 && <span className="text-orange-400">{v.tokens_per_sec_1m}t/s</span>}</div></div>
        ); })}</div>
      </div>)}

      {snaps.length > 2 && (<div className="rounded-xl p-5 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Metrics Over Time</span>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-3">{[
          { key: 'compression_ratio', label: 'Compression', color: '#F0AB00', fmt: (v: number) => `${v}:1` },
          { key: 'projected_clusters', label: 'Clusters', color: 'var(--brand-secondary)', fmt: (v: number) => `${v}` },
          { key: 'avg_latency_ms', label: 'Latency', color: '#EC7A08', fmt: (v: number) => `${v?.toFixed?.(0) ?? 0}ms` },
          { key: 'signals_per_second', label: 'Sig/s', color: '#3E8635', fmt: (v: number) => `${v}` },
          { key: 'reasoning_tasks', label: 'Tasks', color: 'var(--brand-primary)', fmt: (v: number) => `${v}` },
          { key: 'inference_in_flight', label: 'In-Flight', color: '#EC7A08', fmt: (v: number) => `${v}` },
        ].map(({ key, label, color, fmt }) => {
          const values = snaps.slice(-20).map(s => Number((s as Record<string, unknown>)[key]) || 0);
          const max = Math.max(...values, 1); const cur = values[values.length - 1] ?? 0;
          return (<div key={key}><div className="flex justify-between text-xs text-[#6A6E73] mb-1"><span>{label}</span><span style={{ color }} className="font-bold">{fmt(cur)}</span></div><div className="flex items-end gap-px h-8">{values.map((v, i) => (<div key={i} className="flex-1 rounded-t transition-all duration-300" style={{ height: `${Math.max((v / max) * 100, 3)}%`, backgroundColor: color }} />))}</div></div>);
        })}</div>
      </div>)}

      {m && m.raw_signals > 0 && (<div className="rounded-xl p-5 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Signal Funnel</span>
        <div className="mt-2"><FunnelChart funnel={{ raw_signals_received: m.raw_signals, normalized_signals: m.raw_signals, dropped_signals: m.dropped, deduped_signals: 0, suppressed_transients: 0, retained_signals: m.retained, correlated_findings: m.findings, reasoning_tasks_created: m.reasoning_tasks, final_insights_created: m.inference_completed ?? 0, signal_reduction_percent: m.raw_signals > 0 ? (m.dropped / m.raw_signals) * 100 : 0, llm_escalation_rate_percent: m.llm_escalation_pct, reasoning_compression_ratio: m.compression_ratio }} /></div>
      </div>)}

      {receipt && !running && (<section className="rounded-xl p-6 border-2" style={{ borderColor: 'var(--brand-green)' }}>
        <div className="flex items-center justify-between mb-4"><h2 className="text-lg font-semibold" style={{ fontFamily: 'Red Hat Display' }}>Run Receipt</h2><span className="text-xs text-[#3E8635] font-bold uppercase">Completed</span></div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <div className="text-center"><div className="text-3xl font-bold text-white">{Number(receipt.peak_projected_clusters ?? 0).toLocaleString()}</div><div className="text-xs text-[#6A6E73]">Peak Clusters</div></div>
          <div className="text-center"><div className="text-3xl font-bold text-yellow-400">{Number(receipt.max_compression_ratio ?? 0)}:1</div><div className="text-xs text-[#6A6E73]">Best Compression</div></div>
          <div className="text-center"><div className="text-3xl font-bold text-white">{Number(receipt.total_raw_signals ?? 0).toLocaleString()}</div><div className="text-xs text-[#6A6E73]">Total Signals</div></div>
          <div className="text-center"><div className="text-3xl font-bold" style={{ color: 'var(--brand-primary)' }}>{Number(receipt.total_reasoning_tasks ?? 0).toLocaleString()}</div><div className="text-xs text-[#6A6E73]">Total Tasks</div></div>
        </div>
      </section>)}

      {!running && !state?.metrics?.raw_signals && !receipt && (<div className="text-center py-12"><p className="text-lg text-[#6A6E73] mb-2">Continuous streaming — no cycles, no batches.</p><p className="text-sm text-[#6A6E73]">Signals flow continuously. Metrics update every 500ms. Adjust dials live.</p></div>)}
    </div>
  );
}
