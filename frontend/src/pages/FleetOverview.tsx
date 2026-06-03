import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTimeRange } from '../components/TimeRangeContext';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ObsCluster {
  cluster_id: string;
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

interface ObsSignal {
  signal_id: string;
  cluster: string;
  namespace: string;
  resource_kind: string;
  signal_type: string;
  severity: string;
  timestamp: string;
}

interface ObsAgent {
  name: string;
  evaluations: number;
  escalations: number;
  suppressions: number;
  last_decision: string;
}

/* ------------------------------------------------------------------ */
/*  Severity helpers                                                    */
/* ------------------------------------------------------------------ */

const SEV_COLORS: Record<string, string> = {
  critical: '#C9190B',
  high: '#EE0000',
  medium: '#F0AB00',
  low: '#0071C5',
  info: '#6A6E73',
};

function sevColor(sev: string): string {
  return SEV_COLORS[sev?.toLowerCase()] ?? '#6A6E73';
}

function relativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 0) return 'just now';
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function FleetOverview() {
  const navigate = useNavigate();
  const { range } = useTimeRange();

  /* Observatory REST state */
  const [clusters, setClusters] = useState<ObsCluster[] | null>(null);
  const [signals, setSignals] = useState<ObsSignal[] | null>(null);
  const [agents, setAgents] = useState<ObsAgent[] | null>(null);

  /* ----- REST polling for observatory + metrics (windowed) ----- */
  const [windowedMetrics, setWindowedMetrics] = useState<Record<string, unknown> | null>(null);
  const [signalPage, setSignalPage] = useState(0);
  const SIGNALS_PER_PAGE = 10;

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      try {
        const w = `window=${range.key}`;
        const [clRes, sigRes, agRes, mRes] = await Promise.all([
          fetch('/api/v1/observatory/clusters'),
          fetch(`/api/v1/observatory/signals?${w}`),
          fetch(`/api/v1/observatory/agents?${w}`),
          fetch(`/api/v1/metrics?${w}`),
        ]);
        if (cancelled) return;
        const clData = await clRes.json();
        const sigData = await sigRes.json();
        const agData = await agRes.json();
        if (mRes.ok) setWindowedMetrics(await mRes.json());

        if (clData.clusters) {
          const cl = clData.clusters;
          if (Array.isArray(cl)) setClusters(cl);
          else setClusters(Object.entries(cl).map(([id, v]: [string, any]) => ({ cluster_id: id, ...v })));
        }
        if (sigData.signals) {
          if (Array.isArray(sigData.signals)) setSignals(sigData.signals);
          else setSignals([]);
        }
        if (agData.agents) {
          const ag = agData.agents;
          if (Array.isArray(ag)) setAgents(ag);
          else setAgents(Object.entries(ag).map(([name, v]: [string, any]) => ({
            name,
            evaluations: v.total_evaluated ?? 0,
            escalations: v.escalated ?? 0,
            suppressions: v.suppressed ?? 0,
            last_decision: '',
          })));
        }
      } catch { /* */ }
    }

    fetchAll();
    const poll = setInterval(fetchAll, 10000);
    return () => { cancelled = true; clearInterval(poll); };
  }, [range.key]);

  const wm = windowedMetrics as Record<string, unknown> | null;
  const funnel = (wm?.funnel ?? {}) as Record<string, number>;

  /* ----- Derived values (all from windowed metrics, no SSE) ----- */
  const clusterCount = clusters?.length ?? 0;
  const signalsPerSec = (wm?.signals_per_second as number) ?? 0;
  const compressionRatio = (wm?.compression_ratio as number) ?? 0;
  const inFlight = (wm?.inference_in_flight as number) ?? 0;

  /* Funnel values — from windowed /api/v1/metrics endpoint */
  const rawSignals = funnel.raw ?? 0;
  const retained = Math.max(0, funnel.retained ?? 0);
  const findingsCount = funnel.findings ?? 0;
  const reasoningTasks = funnel.tasks ?? 0;
  const inferenceCompleted = funnel.inferences ?? 0;

  const funnelSteps = [
    { label: 'Raw', value: rawSignals, color: '#6A6E73' },
    { label: 'Retained', value: retained, color: '#0071C5' },
    { label: 'Findings', value: findingsCount, color: '#F0AB00' },
    { label: 'Tasks', value: Math.round(reasoningTasks), color: 'var(--brand-primary, #EE0000)' },
    { label: 'Inferences', value: inferenceCompleted, color: '#3E8635' },
  ];
  const funnelMax = Math.max(...funnelSteps.map((s) => s.value), 1);

  /* Model stats — from windowed metrics */
  const wmModels = (wm?.models ?? {}) as Record<string, { total_calls?: number; calls?: number; avg_latency?: number; avg_tps?: number }>;
  const modelEntries = Object.entries(wmModels).map(([name, v]) => [name, {
    calls: v.total_calls ?? v.calls ?? 0,
    avg_latency: v.avg_latency ?? 0,
    avg_tps: v.avg_tps ?? 0,
  }] as [string, { calls: number; avg_latency: number; avg_tps: number }]);
  const isMicroModel = (name: string) => {
    const l = name.toLowerCase();
    return l.includes('cpu') || l.includes('xeon') || l.includes('granite_2b') || l.includes('phi3_mini') || l.includes('qwen25');
  };
  const microModels = modelEntries.filter(([name]) => isMicroModel(name));
  const macroModels = modelEntries.filter(([name]) => !isMicroModel(name));

  /* Recent signals — from observatory or windowed metrics fallback */
  const obsSignals = signals ?? [];
  const wmSignals = ((wm?.recent_signals ?? []) as ObsSignal[]);
  const recentSignals = (obsSignals.length > 0 ? obsSignals : wmSignals).slice(-20).reverse();

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">

      {/* ============================================================ */}
      {/*  Header                                                       */}
      {/* ============================================================ */}
      <div className="flex items-center justify-between">
        <div>
          <h1
            className="text-3xl font-bold text-white mb-1"
            style={{ fontFamily: 'Red Hat Display, sans-serif' }}
          >
            Fleet Overview
          </h1>
          <p className="text-sm text-[#6A6E73]">Signal intelligence across your fleet</p>
        </div>
        {!windowedMetrics && (
          <div className="flex items-center gap-2 text-xs text-[#6A6E73]">
            <span className="w-2 h-2 rounded-full bg-[#6A6E73] animate-pulse" />
            Loading metrics...
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  1. Stats Bar — 4 metric cards                                */}
      {/* ============================================================ */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Clusters Monitored', value: clusterCount || '0' },
          { label: 'Signals / sec', value: signalsPerSec ? signalsPerSec.toFixed(0) : '0' },
          {
            label: 'Compression Ratio',
            value: compressionRatio != null ? `${compressionRatio}:1` : '—:1',
          },
          { label: 'Active Inferences', value: inFlight },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4"
          >
            <div
              className="text-2xl font-bold text-white tabular-nums"
              style={{ fontFamily: 'Red Hat Display, sans-serif' }}
            >
              {value}
            </div>
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
              {label}
            </div>
          </div>
        ))}
      </div>

      {/* ============================================================ */}
      {/*  2. Cluster cards (moved up, closer to stats)                 */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">Clusters</div>
        </div>
        {clusters === null ? (
          <div className="animate-pulse grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {[1,2,3].map(i => (
              <div key={i} className="bg-[#212121] rounded-lg h-28" />
            ))}
          </div>
        ) : clusters.length === 0 ? (
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-5 text-center">
            <div className="text-sm text-[#6A6E73]">
              No clusters connected &mdash; configure <code className="text-xs bg-[#1a1a1a] px-1.5 py-0.5 rounded text-white">CLUSTER_1_*</code> env vars
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {clusters.map((cl) => (
              <div
                key={cl.cluster_id}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 cursor-pointer hover:border-[#555] transition-colors"
                onClick={() => navigate(`/cluster/${cl.cluster_id}`)}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-semibold text-white">{cl.cluster_id}</span>
                  <span className="text-[10px] text-[#6A6E73]">{cl.last_scan ? relativeTime(cl.last_scan) : ''}</span>
                </div>
                <div className="grid grid-cols-5 gap-2 text-center mb-3">
                  {[
                    { v: cl.total_pods, l: 'Pods', c: 'text-white' },
                    { v: cl.pods_running, l: 'Running', c: 'text-[#3E8635]' },
                    { v: cl.pods_pending, l: 'Pending', c: 'text-[#F0AB00]' },
                    { v: cl.pods_crashloop, l: 'Crash', c: 'text-[#C9190B]' },
                    { v: cl.total_nodes, l: 'Nodes', c: 'text-white' },
                  ].map(({ v, l, c }) => (
                    <div key={l}>
                      <div className={`text-base font-bold tabular-nums ${c}`} style={{ fontFamily: 'Red Hat Display' }}>{v ?? 0}</div>
                      <div className="text-[8px] text-[#6A6E73] uppercase">{l}</div>
                    </div>
                  ))}
                </div>
                {cl.total_pods > 0 && (
                  <div className="h-1.5 flex rounded-full overflow-hidden gap-px">
                    <div style={{ width: `${((cl.pods_running ?? 0) / cl.total_pods) * 100}%`, backgroundColor: '#3E8635' }} />
                    <div style={{ width: `${((cl.pods_pending ?? 0) / cl.total_pods) * 100}%`, backgroundColor: '#F0AB00' }} />
                    <div style={{ width: `${(((cl.pods_failed ?? 0) + (cl.pods_crashloop ?? 0)) / cl.total_pods) * 100}%`, backgroundColor: '#C9190B' }} />
                  </div>
                )}
                {cl.total_events_warning > 0 && (
                  <div className="text-[10px] text-[#F0AB00] mt-2">{cl.total_events_warning} warning events</div>
                )}
                <div className="text-[10px] text-[#0071C5] mt-1">Click for namespace detail →</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  3. Signal Funnel — compact horizontal bar                    */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Signal Funnel
        </div>
        <div className="flex items-end gap-2 h-10">
          {funnelSteps.map(({ label, value, color }) => {
            const pct = funnelMax > 0 ? Math.max((value / funnelMax) * 100, 4) : 4;
            return (
              <div key={label} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-xs text-white font-bold tabular-nums">
                  {value.toLocaleString()}
                </span>
                <div
                  className="w-full rounded-t"
                  style={{
                    height: `${pct}%`,
                    minHeight: '4px',
                    backgroundColor: color,
                  }}
                />
                <span className="text-[10px] text-[#6A6E73]">{label}</span>
              </div>
            );
          })}
        </div>
        {/* Arrow connectors */}
        <div className="flex items-center justify-center gap-0 mt-1">
          {funnelSteps.slice(0, -1).map((_, i) => (
            <div key={i} className="flex-1 flex items-center justify-center">
              <span className="text-[#6A6E73] text-[10px]">{'→'}</span>
            </div>
          ))}
          <div className="flex-1" />
        </div>
      </div>

      {/* ============================================================ */}
      {/*  3. Micro-Agents (Nano — Deterministic Filters)               */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
            Nano-Agents <span className="text-[#0071C5]">· Deterministic Filters</span>
          </div>
          <button onClick={() => navigate('/pipeline')} className="text-xs text-[#0071C5] hover:text-white transition">
            View Pipeline →
          </button>
        </div>
        {agents === null ? (
          <div className="animate-pulse grid grid-cols-2 gap-3">
            {[1,2,3,4].map(i => <div key={i} className="bg-[#212121] rounded-lg h-20" />)}
          </div>
        ) : agents.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">Pipeline initializing...</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {agents.map((agent) => {
              const escRate = agent.evaluations > 0 ? (agent.escalations / agent.evaluations) * 100 : 0;
              const dotColor = escRate < 5 ? '#3E8635' : escRate < 20 ? '#F0AB00' : '#C9190B';
              return (
                <div key={agent.name}
                  className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 cursor-pointer hover:border-[#555] transition-colors"
                  onClick={() => navigate('/pipeline')}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dotColor }} />
                    <span className="text-xs font-medium text-white truncate">{agent.name.replace('Agent', '')}</span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-lg font-bold text-white tabular-nums" style={{ fontFamily: 'Red Hat Display' }}>{agent.evaluations.toLocaleString()}</span>
                    <span className="text-[10px] text-[#6A6E73]">evals</span>
                  </div>
                  <div className="text-[10px] tabular-nums mt-1">
                    <span style={{ color: dotColor }}>{escRate.toFixed(0)}% esc</span>
                    <span className="text-[#6A6E73]"> · {agent.escalations} escalated</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  4a. Micro-Agents (Xeon 6 CPU — Fast Triage)                  */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
            Micro-Agents <span className="text-[#0071C5]">· Xeon 6 Triage</span>
          </div>
          <button onClick={() => navigate('/llm')} className="text-xs text-[#0071C5] hover:text-white transition">
            View Details →
          </button>
        </div>
        <p className="text-[10px] text-[#6A6E73] mb-3">Fast CPU inference for signal classification, correlation, remediation suggestions</p>
        {microModels.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No micro models active — waiting for triage tasks</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {microModels.map(([model, stats]) => (
              <div key={model}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 cursor-pointer hover:border-[#555] transition-colors"
                onClick={() => navigate('/llm')}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ backgroundColor: '#0071C520', color: '#0071C5' }}>Xeon 6</span>
                  <span className="text-xs text-[#6A6E73] truncate font-mono">{model.replace(/_/g, ' ')}</span>
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-lg font-bold text-white tabular-nums" style={{ fontFamily: 'Red Hat Display' }}>{stats.calls}</span>
                  <span className="text-[10px] text-[#6A6E73]">calls</span>
                </div>
                <div className="text-[10px] text-[#0071C5] tabular-nums mt-1">
                  {stats.avg_tps} tok/s · {stats.avg_latency}ms
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  4b. Macro-Agents (Gaudi 3 GPU — Deep Reasoning)              */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
            Macro-Agents <span className="text-[#EE0000]">· Gaudi 3 Reasoning</span>
          </div>
          <button onClick={() => navigate('/llm')} className="text-xs text-[#EE0000] hover:text-white transition">
            View Details →
          </button>
        </div>
        <p className="text-[10px] text-[#6A6E73] mb-3">GPU inference for root cause analysis, incident creation, capacity forecasting</p>
        {macroModels.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No macro models active — waiting for high-severity escalations</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {macroModels.map(([model, stats]) => (
              <div key={model}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 cursor-pointer hover:border-[#555] transition-colors"
                onClick={() => navigate('/llm')}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ backgroundColor: '#EE000020', color: '#EE0000' }}>Gaudi 3</span>
                  <span className="text-xs text-[#6A6E73] truncate font-mono">{model.replace(/_/g, ' ')}</span>
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-lg font-bold text-white tabular-nums" style={{ fontFamily: 'Red Hat Display' }}>{stats.calls}</span>
                  <span className="text-[10px] text-[#6A6E73]">calls</span>
                </div>
                <div className="text-[10px] text-[#EE0000] tabular-nums mt-1">
                  {stats.avg_tps} tok/s · {stats.avg_latency}ms
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  5. Recent Signals — paginated                                */}
      {/* ============================================================ */}
      {(() => {
        const totalSignals = recentSignals.length;
        const totalPages = Math.max(1, Math.ceil(totalSignals / SIGNALS_PER_PAGE));
        const page = Math.min(signalPage, totalPages - 1);
        const pageSignals = recentSignals.slice(page * SIGNALS_PER_PAGE, (page + 1) * SIGNALS_PER_PAGE);
        return (
          <div className="border border-[#333] rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
                Recent Signals {totalSignals > 0 && <span className="text-white">({totalSignals})</span>}
              </div>
              {totalPages > 1 && (
                <div className="flex items-center gap-2">
                  <button onClick={() => setSignalPage(Math.max(0, page - 1))} disabled={page === 0}
                    className="px-2 py-0.5 rounded text-xs font-bold bg-[#212121] text-[#6A6E73] hover:text-white disabled:opacity-30">
                    ‹
                  </button>
                  <span className="text-xs text-[#6A6E73] tabular-nums">{page + 1} / {totalPages}</span>
                  <button onClick={() => setSignalPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
                    className="px-2 py-0.5 rounded text-xs font-bold bg-[#212121] text-[#6A6E73] hover:text-white disabled:opacity-30">
                    ›
                  </button>
                </div>
              )}
            </div>
            {signals === null ? (
              <div className="animate-pulse space-y-2">
                {[1,2,3].map(i => (
                  <div key={i} className="bg-[#212121] rounded-lg h-8" />
                ))}
              </div>
            ) : recentSignals.length === 0 ? (
              <div className="text-sm text-[#6A6E73]">Monitoring active &mdash; waiting for signals</div>
            ) : (
              <div className="space-y-1">
                {pageSignals.map((sig) => (
                  <div
                    key={sig.signal_id ?? `${sig.cluster}-${sig.timestamp}-${sig.signal_type}`}
                    className="flex items-center gap-3 bg-[#1a1a1a] rounded-lg px-3 py-2 text-xs cursor-pointer hover:bg-[#252525]"
                    onClick={() => navigate(`/cluster/${sig.cluster}`)}
                  >
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                      style={{ color: sevColor(sig.severity), backgroundColor: `${sevColor(sig.severity)}20` }}
                    >
                      {sig.severity}
                    </span>
                    <span className="text-white font-medium truncate max-w-[160px]">{sig.signal_type}</span>
                    <span className="text-[#9CA3AF] truncate max-w-[120px]">{sig.namespace}</span>
                    <span className="text-[#6A6E73] truncate max-w-[120px]">{sig.cluster}</span>
                    <span className="text-[#6A6E73] ml-auto whitespace-nowrap">
                      {sig.timestamp ? relativeTime(sig.timestamp) : '—'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
