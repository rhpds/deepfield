import { useState, useEffect } from 'react';
import type { ClusterMetrics } from '../api/client';
import FunnelChart from '../components/FunnelChart';
import PressureGauge from '../components/PressureGauge';

interface StreamState {
  session_id: string;
  status: string;
  metrics: Record<string, number>;
  totals: Record<string, number>;
  model_stats: Record<string, { calls: number; avg_latency: number; avg_tps: number }>;
  live_inference: { last_model?: string; last_latency_ms?: number; in_flight?: number; completed?: number };
  snapshots: Array<Record<string, unknown>>;
  queue_depth: number;
}

interface ClusterInfo {
  cluster_name: string;
  total_pods: number;
  pods_running: number;
  pods_pending: number;
  pods_failed: number;
  pods_crashloop: number;
  total_nodes: number;
  nodes_ready: number;
  nodes_pressure: number;
  total_events_warning: number;
  namespaces: Record<string, number>;
  last_scan: string;
}

interface Signal {
  signal_type: string;
  namespace: string;
  resource_kind: string;
  resource_name: string;
  cluster: string;
  raw_payload: Record<string, unknown>;
  _ts: string;
  [key: string]: unknown;
}

export default function LiveMonitoring() {
  const [state, setState] = useState<StreamState | null>(null);
  const [cluster, setCluster] = useState<ClusterMetrics | null>(null);
  const [agentLog, setAgentLog] = useState<Array<Record<string, unknown>>>([]);

  const [clusters, setClusters] = useState<Record<string, ClusterInfo>>({});
  const [signals, setSignals] = useState<Signal[]>([]);
  const [findings, setFindings] = useState<Array<Record<string, unknown>>>([]);
  const [expandedSignal, setExpandedSignal] = useState<number | null>(null);
  const [expandedCluster, setExpandedCluster] = useState<string | null>(null);
  const [signalFilter, setSignalFilter] = useState<{ cluster?: string; severity?: string }>({});

  useEffect(() => {
    // SSE for real-time updates
    const es = new EventSource('/api/v1/stream');
    es.addEventListener('live', (e) => { try { const d = JSON.parse(e.data); if (d.metrics) { setState(d); if (d.agent_log) setAgentLog(d.agent_log); } } catch {} });
    es.addEventListener('cluster', (e) => { try { const d = JSON.parse(e.data); if (d.available) setCluster(d); } catch {} });

    // Polling fallback in case SSE doesn't connect
    const poll = setInterval(async () => {
      try {
        const resp = await fetch('/api/v1/session/live/state');
        const d = await resp.json();
        if (d.metrics) { setState(d); if (d.agent_log) setAgentLog(d.agent_log); }
      } catch { /* */ }
    }, 2000);

    return () => { es.close(); clearInterval(poll); };
  }, []);

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const [clResp, sigResp] = await Promise.all([
          fetch('/api/v1/observatory/clusters'),
          fetch('/api/v1/observatory/signals'),
        ]);
        const clData = await clResp.json();
        const sigData = await sigResp.json();
        if (clData.clusters) setClusters(clData.clusters);
        if (sigData.signals) setSignals(sigData.signals);
        if (sigData.findings) setFindings(sigData.findings);
      } catch { /* */ }
    }, 3000);
    return () => clearInterval(poll);
  }, []);

  const m = state?.metrics;
  const t = state?.totals;
  const snaps = state?.snapshots || [];
  const cm = cluster?.models ?? {};
  const hasData = (t?.raw_signals ?? 0) > 0 || signals.length > 0 || agentLog.length > 0;
  const cmVals = Object.values(cm) as Array<Record<string, number | undefined>>;
  const clusterRunning = cmVals.reduce((s, v) => s + (Number(v.requests_running) || 0), 0);
  const clusterTps = cmVals.reduce((s, v) => s + (Number(v.tokens_per_sec_1m) || 0), 0);

  const filteredSignals = signals.filter(s => {
    if (signalFilter.cluster && s.cluster !== signalFilter.cluster) return false;
    if (signalFilter.severity) {
      const sev = String((s as Record<string, unknown>).severity ?? s.signal_type ?? '');
      if (!sev.includes(signalFilter.severity)) return false;
    }
    return true;
  });

  const clusterNames = Object.keys(clusters);

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white" style={{ fontFamily: 'Red Hat Display' }}>Live Cluster Monitoring</h2>
          <p className="text-xs text-[#6A6E73] mt-1">Real-time OpenShift fleet signal intelligence — always on</p>
        </div>
        {state?.status === 'running' && (
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#3E8635] animate-pulse" />
            <span className="text-xs text-[#3E8635] font-medium">LIVE</span>
          </div>
        )}
      </div>

      {/* Cluster Infrastructure Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {(clusterNames.length > 0 ? clusterNames : []).map(name => {
          const info = clusters[name];
          const isExpanded = expandedCluster === name;
          const meta = { location: '', desc: '' };

          return (
            <div key={name} className={`rounded-xl border ${state ? 'border-[#3E8635]' : 'border-[#333]'} overflow-hidden`}>
              <div className="p-4 cursor-pointer hover:bg-[#1a1a1a]" onClick={() => setExpandedCluster(isExpanded ? null : name)}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">{name}</span>
                    {state && <span className="w-2 h-2 rounded-full bg-[#3E8635] animate-pulse" />}
                  </div>
                  <span className="text-[10px] text-[#6A6E73]">{isExpanded ? '▲' : '▼'}</span>
                </div>
                <div className="text-[10px] text-[#6A6E73] mb-2">{meta.location}{meta.desc ? ` — ${meta.desc}` : ''}</div>

                {info ? (
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <div className="text-lg font-bold text-white tabular-nums">{info.total_pods}</div>
                      <div className="text-[9px] text-[#6A6E73]">Pods</div>
                      <div className="flex gap-1 justify-center mt-0.5 text-[9px] tabular-nums">
                        <span className="text-[#3E8635]">{info.pods_running}r</span>
                        {info.pods_pending > 0 && <span className="text-yellow-400">{info.pods_pending}p</span>}
                        {info.pods_crashloop > 0 && <span className="text-red-400">{info.pods_crashloop}c</span>}
                        {info.pods_failed > 0 && <span className="text-red-400">{info.pods_failed}f</span>}
                      </div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-white tabular-nums">{info.total_nodes}</div>
                      <div className="text-[9px] text-[#6A6E73]">Nodes</div>
                      <div className="flex gap-1 justify-center mt-0.5 text-[9px] tabular-nums">
                        <span className="text-[#3E8635]">{info.nodes_ready}r</span>
                        {info.nodes_pressure > 0 && <span className="text-red-400">{info.nodes_pressure}p</span>}
                      </div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-white tabular-nums">{Object.keys(info.namespaces).length}</div>
                      <div className="text-[9px] text-[#6A6E73]">Namespaces</div>
                      {info.total_events_warning > 0 && (
                        <div className="text-[9px] text-yellow-400 mt-0.5">{info.total_events_warning} warn</div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-[#6A6E73]">Waiting for first scan...</div>
                )}
              </div>

              {isExpanded && info && Object.keys(info.namespaces).length > 0 && (
                <div className="border-t border-[#333] p-3 bg-[#1a1a1a]">
                  <div className="text-[10px] text-[#6A6E73] uppercase mb-1 font-semibold">Namespaces ({Object.keys(info.namespaces).length})</div>
                  <div className="grid grid-cols-2 gap-1">
                    {Object.entries(info.namespaces).sort((a, b) => b[1] - a[1]).map(([ns, count]) => (
                      <div key={ns} className="flex items-center justify-between text-[11px] px-2 py-0.5 rounded bg-[#252525]">
                        <span className="text-[#9CA3AF] truncate">{ns}</span>
                        <span className="text-white font-bold tabular-nums ml-2">{count}</span>
                      </div>
                    ))}
                  </div>
                  {info.last_scan && (
                    <div className="text-[9px] text-[#6A6E73] mt-2">Last scan: {new Date(info.last_scan).toLocaleTimeString()}</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Waiting for first signals */}
      {!hasData && !Object.keys(clusters).length && (
        <div className="rounded-xl p-8 border border-[#333] text-center">
          <div className="w-3 h-3 rounded-full animate-pulse mx-auto mb-3" style={{ backgroundColor: 'var(--brand-green)' }} />
          <div className="text-lg text-[#e0e0e0]">Connecting to clusters...</div>
          <div className="text-sm text-[#6A6E73] mt-1">Scanning pods, nodes, routes, PVCs, and events across configured clusters.</div>
        </div>
      )}

      {/* Inline stats — replaces projected fleet coverage hero */}
      {hasData && m && (
        <div className="flex gap-4">
          <div className="flex gap-3 rounded-xl p-4 border border-[#333] items-center">
            <PressureGauge value={clusterRunning} max={50} label="Running" />
            <PressureGauge value={Math.round(clusterTps)} max={500} label="Tok/s" />
            <PressureGauge value={m.inference_in_flight ?? 0} max={20} label="In-Flight" />
          </div>
          <div className="flex-1 rounded-xl p-4 border border-[#333]">
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-3xl font-bold text-white tabular-nums">{(t?.raw_signals ?? 0).toLocaleString()}</div>
                <div className="text-[10px] text-[#6A6E73]">Signals Processed</div>
              </div>
              <div>
                <div className="text-3xl font-bold text-yellow-400 tabular-nums">{m.compression_ratio}:1</div>
                <div className="text-[10px] text-[#6A6E73]">Compression Ratio</div>
              </div>
              <div>
                <div className="text-3xl font-bold tabular-nums" style={{ color: 'var(--brand-primary)' }}>{(m.llm_escalation_pct ?? 0).toFixed(2)}%</div>
                <div className="text-[10px] text-[#6A6E73]">Escalation Rate</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Live Metrics */}
      {hasData && m && (
        <>
          <div className="grid grid-cols-3 md:grid-cols-7 gap-2">
            {[
              { v: String((t?.raw_signals ?? 0) || m.raw_signals).toLocaleString(), l: 'Signals', c: 'text-white' },
              { v: `${m.compression_ratio}:1`, l: 'Compression', c: 'text-yellow-400' },
              { v: String(Math.round(m.reasoning_tasks ?? 0)), l: 'Tasks', c: '', s: { color: 'var(--brand-primary)' } },
              { v: `${(m.llm_escalation_pct ?? 0).toFixed(2)}%`, l: 'Escalation', c: 'text-[#3E8635]' },
              { v: String(Math.round(m.avg_tps ?? 0)), l: 'Tok/s', c: 'text-orange-400' },
              { v: `${Math.round(m.avg_latency_ms ?? 0)}ms`, l: 'Latency', c: '', s: { color: 'var(--brand-secondary)' } },
              { v: String(m.inference_in_flight ?? 0), l: 'In-Flight', c: 'text-orange-400' },
            ].map(({ v, l, c, s }, i) => (
              <div key={i} className="rounded-lg p-2 border border-[#333] text-center">
                <div className={`text-lg font-bold tabular-nums ${c}`} style={s}>{v}</div>
                <div className="text-[10px] text-[#6A6E73]">{l}</div>
              </div>
            ))}
          </div>
          {t && (
            <div className="rounded-lg p-3 border border-[#333] flex flex-wrap items-center justify-between gap-3">
              <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Cumulative</span>
              <div className="flex flex-wrap gap-4 text-xs tabular-nums">
                <span><span className="text-[#6A6E73]">Signals:</span> <span className="text-white font-bold">{(t.raw_signals ?? 0).toLocaleString()}</span></span>
                <span><span className="text-[#6A6E73]">Tasks:</span> <span className="font-bold" style={{ color: 'var(--brand-primary)' }}>{(t.reasoning_tasks ?? 0).toLocaleString()}</span></span>
                <span><span className="text-[#6A6E73]">Comp:</span> <span className="text-yellow-400 font-bold">{t.cumulative_compression_ratio ?? 0}:1</span></span>
                <span><span className="text-[#6A6E73]">Inference:</span> <span className="text-orange-400 font-bold">{(t.inference_calls ?? 0).toLocaleString()}</span></span>
              </div>
            </div>
          )}
        </>
      )}

      {/* Signal Feed — clickable with full detail */}
      {signals.length > 0 && (
        <div className="rounded-xl p-4 border border-[#333]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Signal Feed ({filteredSignals.length})</span>
            <div className="flex gap-1">
              <button onClick={() => setSignalFilter({})} className={`px-2 py-0.5 rounded text-[10px] ${!signalFilter.cluster && !signalFilter.severity ? 'bg-[#333] text-white' : 'text-[#6A6E73]'}`}>All</button>
              {clusterNames.map(c => (
                <button key={c} onClick={() => setSignalFilter(f => ({ ...f, cluster: f.cluster === c ? undefined : c }))}
                  className={`px-2 py-0.5 rounded text-[10px] ${signalFilter.cluster === c ? 'bg-[#3E8635] text-white' : 'text-[#6A6E73]'}`}>{c}</button>
              ))}
              {['crashloop', 'pressure', 'pending'].map(sev => (
                <button key={sev} onClick={() => setSignalFilter(f => ({ ...f, severity: f.severity === sev ? undefined : sev }))}
                  className={`px-2 py-0.5 rounded text-[10px] ${signalFilter.severity === sev ? 'bg-orange-600 text-white' : 'text-[#6A6E73]'}`}>{sev}</button>
              ))}
            </div>
          </div>
          <div className="space-y-1 max-h-[400px] overflow-y-auto">
            {filteredSignals.slice().reverse().slice(0, 50).map((sig, i) => {
              const isExpanded = expandedSignal === i;
              const isWarning = sig.signal_type.includes('crash') || sig.signal_type.includes('fail') || sig.signal_type.includes('pressure') || sig.signal_type.includes('error');
              return (
                <div key={i} className={`bg-[#1a1a1a] rounded border-l-2 cursor-pointer hover:bg-[#252525] ${isWarning ? 'border-orange-400' : 'border-[#333]'}`}
                  onClick={() => setExpandedSignal(isExpanded ? null : i)}>
                  <div className="p-2 flex items-center gap-2 text-xs">
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${sig.cluster.includes('infra') ? 'bg-[#0071C5]/20 text-[#0071C5]' : 'bg-orange-400/20 text-orange-400'}`}>
                      {sig.cluster}
                    </span>
                    <span className="text-[#9CA3AF] truncate max-w-[120px]">{sig.namespace}</span>
                    <span className={`font-medium ${isWarning ? 'text-orange-400' : 'text-white'}`}>{sig.signal_type}</span>
                    <span className="text-[#6A6E73] truncate max-w-[150px]">{sig.resource_name}</span>
                    <span className="text-[#6A6E73] ml-auto text-[10px]">{sig._ts ? new Date(sig._ts).toLocaleTimeString() : ''}</span>
                    <span className="text-[#6A6E73]">{isExpanded ? '▲' : '▼'}</span>
                  </div>
                  {isExpanded && (
                    <div className="px-2 pb-2">
                      <div className="text-[10px] text-[#6A6E73] uppercase mb-0.5">Raw Payload</div>
                      <pre className="bg-[#252525] rounded p-2 text-[11px] text-[#9CA3AF] whitespace-pre-wrap max-h-40 overflow-y-auto font-mono">
                        {JSON.stringify(sig.raw_payload || sig, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Correlation Findings */}
      {findings.length > 0 && (
        <div className="rounded-xl p-4 border border-[#333]">
          <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Correlation Findings ({findings.length})</span>
          <div className="mt-2 space-y-1 max-h-60 overflow-y-auto">
            {findings.slice().reverse().map((f, i) => {
              const sev = String(f.severity ?? '');
              const sevColor = sev === 'critical' ? 'border-red-500' : sev === 'high' ? 'border-orange-400' : 'border-yellow-400';
              return (
                <div key={i} className={`bg-[#1a1a1a] rounded p-2 text-xs border-l-2 ${sevColor}`}>
                  <div className="flex items-center gap-2">
                    <span className="text-white font-medium">{String(f.finding_type ?? '')}</span>
                    <span className={`text-[10px] px-1 rounded ${sev === 'critical' ? 'bg-red-900/50 text-red-300' : sev === 'high' ? 'bg-orange-900/50 text-orange-300' : 'bg-yellow-900/50 text-yellow-300'}`}>{sev}</span>
                    <span className="text-[#6A6E73]">{String(f.signal_count ?? '')} signals</span>
                    {f.clusters ? <span className="text-[#6A6E73]">{(f.clusters as string[]).join(', ')}</span> : null}
                    <span className="text-[#6A6E73] ml-auto text-[10px]">{f._ts ? new Date(String(f._ts)).toLocaleTimeString() : ''}</span>
                  </div>
                  <div className="text-[#9CA3AF] mt-0.5">{String(f.summary ?? '')}</div>
                  {f.namespaces ? <div className="text-[10px] text-[#6A6E73] mt-0.5">ns: {(f.namespaces as string[]).join(', ')}</div> : null}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Model Performance */}
      {state?.model_stats && Object.keys(state.model_stats).length > 0 && (
        <div className="rounded-xl p-4 border border-[#333]">
          <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Agent Performance (Micro ▼ Xeon 6 / Macro ▲ Gaudi 3)</span>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">{Object.entries(state.model_stats).map(([model, stats]) => {
            const isMicro = model.includes('cpu') || model.includes('granite') || model.includes('phi3_mini') || model.includes('qwen25');
            return (
              <div key={model} className={`bg-[#1a1a1a] rounded p-2 border-l-2 ${isMicro ? 'border-[#0071C5]' : 'border-orange-400'}`}>
                <div className="flex items-center gap-1">
                  <span className={`text-[10px] ${isMicro ? 'text-[#0071C5]' : 'text-orange-400'}`}>{isMicro ? '▼' : '▲'}</span>
                  <span className="text-[10px] font-mono text-[#6A6E73] truncate">{model.split('_').slice(0, 2).join('_')}</span>
                </div>
                <div className="text-lg font-bold text-white mt-1">{stats.calls} <span className="text-[10px] text-[#6A6E73]">calls</span></div>
                <div className="text-xs text-orange-400">{stats.avg_tps} tok/s | {stats.avg_latency}ms</div>
              </div>
            );
          })}</div>
        </div>
      )}

      {/* Agent Pipeline Log */}
      {agentLog.length > 0 && (
        <div className="rounded-xl p-4 border border-[#333]">
          <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Agent Pipeline (Live)</span>
          <div className="mt-2 space-y-1 max-h-80 overflow-y-auto">
            {agentLog.slice().reverse().map((event, i) => {
              const tier = String(event.tier ?? '');
              const action = String(event.action ?? '');
              const isNano = tier === 'nano';
              const isMicro = tier === 'micro';
              const isMacro = tier === 'macro';
              const isCorrelation = tier === 'correlation';
              const borderColor = isNano ? '#6A6E73' : isMicro ? '#0071C5' : isMacro ? '#EC7A08' : isCorrelation ? '#F0AB00' : '#333';
              const tierLabel = isNano ? 'NANO' : isMicro ? 'MICRO ▼' : isMacro ? 'MACRO ▲' : isCorrelation ? 'CORR' : tier.toUpperCase();
              const tierColor = isNano ? 'text-[#6A6E73]' : isMicro ? 'text-[#0071C5]' : isMacro ? 'text-orange-400' : 'text-yellow-400';

              return (
                <div key={i} className="bg-[#1a1a1a] rounded p-2 border-l-2 text-xs" style={{ borderColor }}>
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={`font-bold text-[10px] ${tierColor}`}>{tierLabel}</span>
                    <span className="text-white font-medium">{action}</span>
                    {event.model ? <span className="text-[#6A6E73] font-mono">{String(event.model).split('_').slice(0, 2).join('_')}</span> : null}
                    {event.severity ? <span className={`text-[10px] px-1 rounded ${String(event.severity) === 'critical' ? 'bg-red-900/50 text-red-300' : String(event.severity) === 'high' ? 'bg-orange-900/50 text-orange-300' : 'bg-yellow-900/50 text-yellow-300'}`}>{String(event.severity)}</span> : null}
                    {event.latency_ms ? <span className="text-[#6A6E73]">{String(event.latency_ms)}ms</span> : null}
                    {event.tokens ? <span className="text-orange-400">{String(event.tokens)}tok</span> : null}
                    <span className="text-[#6A6E73] ml-auto text-[10px]">{event.ts ? new Date(String(event.ts)).toLocaleTimeString() : ''}</span>
                  </div>
                  {event.output ? (
                    <div className="text-[#9CA3AF] mt-0.5 text-[11px] leading-tight truncate">
                      {String(event.output).slice(0, 120)}
                    </div>
                  ) : null}
                  {event.summary ? (
                    <div className="text-[#9CA3AF] mt-0.5 text-[11px] leading-tight">
                      {String(event.summary)}
                    </div>
                  ) : null}
                  {event.reason && !event.output ? (
                    <div className="text-[#6A6E73] text-[10px]">{String(event.reason)}</div>
                  ) : null}
                  {event.namespaces ? (
                    <div className="text-[#6A6E73] text-[10px]">ns: {(event.namespaces as string[]).join(', ')}</div>
                  ) : null}
                  {event.prompt ? (
                    <div className="text-[#6A6E73] text-[10px] truncate">prompt: {String(event.prompt)}</div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Inference Cluster Pressure */}
      {cluster?.available && (
        <div className="rounded-xl p-4 border border-[#333]">
          <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Inference Cluster (Prometheus)</span>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">{Object.entries(cm).map(([model, mv]) => {
            const v = mv as Record<string, number | undefined>;
            return (
              <div key={model} className={`bg-[#1a1a1a] rounded p-2 border-l-2 ${(Number(v.requests_running) || 0) > 0 ? 'border-[#3E8635]' : 'border-[#333]'}`}>
                <div className="text-[10px] font-mono text-[#6A6E73] truncate">{model}</div>
                <div className="flex gap-2 mt-1 text-xs tabular-nums">
                  <span className={(Number(v.requests_running) || 0) > 0 ? 'text-[#3E8635] font-bold' : 'text-[#333]'}>{v.requests_running ?? 0}r</span>
                  <span className={(Number(v.requests_waiting) || 0) > 0 ? 'text-yellow-400' : 'text-[#333]'}>{v.requests_waiting ?? 0}q</span>
                  {(Number(v.tokens_per_sec_1m) || 0) > 0 && <span className="text-orange-400">{v.tokens_per_sec_1m}t/s</span>}
                </div>
              </div>
            );
          })}</div>
        </div>
      )}

      {/* Time Series */}
      {snaps.length > 2 && (
        <div className="rounded-xl p-5 border border-[#333]">
          <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Metrics Over Time</span>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-3">{[
            { key: 'compression_ratio', label: 'Compression', color: '#F0AB00', fmt: (v: number) => `${v}:1` },
            { key: 'reasoning_tasks', label: 'Reasoning Tasks', color: 'var(--brand-primary)', fmt: (v: number) => `${v}` },
            { key: 'avg_latency_ms', label: 'Latency', color: '#EC7A08', fmt: (v: number) => `${v?.toFixed?.(0) ?? 0}ms` },
          ].map(({ key, label, color, fmt }) => {
            const vals = snaps.slice(-20).map(s => Number((s as Record<string, unknown>)[key]) || 0);
            const max = Math.max(...vals, 1); const cur = vals[vals.length - 1] ?? 0;
            return (<div key={key}><div className="flex justify-between text-xs text-[#6A6E73] mb-1"><span>{label}</span><span style={{ color }} className="font-bold">{fmt(cur)}</span></div><div className="flex items-end gap-px h-8">{vals.map((v, i) => (<div key={i} className="flex-1 rounded-t transition-all duration-300" style={{ height: `${Math.max((v / max) * 100, 3)}%`, backgroundColor: color }} />))}</div></div>);
          })}</div>
        </div>
      )}

      {/* Signal Funnel */}
      {hasData && m && (
        <div className="rounded-xl p-5 border border-[#333]">
          <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Signal Funnel (Live)</span>
          <div className="mt-2"><FunnelChart funnel={{ raw_signals_received: m.raw_signals, normalized_signals: m.raw_signals, dropped_signals: m.dropped ?? 0, deduped_signals: 0, suppressed_transients: 0, retained_signals: m.retained ?? 0, correlated_findings: m.findings ?? 0, reasoning_tasks_created: Math.round(m.reasoning_tasks ?? 0), final_insights_created: m.inference_completed ?? 0, signal_reduction_percent: m.raw_signals > 0 ? ((m.dropped ?? 0) / m.raw_signals) * 100 : 0, llm_escalation_rate_percent: m.llm_escalation_pct ?? 0, reasoning_compression_ratio: m.compression_ratio ?? 0 }} /></div>
        </div>
      )}

    </div>
  );
}
