import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StreamState {
  session_id: string;
  status: string;
  metrics: Record<string, number>;
  totals: Record<string, number>;
  model_stats: Record<string, { calls: number; avg_latency: number; avg_tps: number }>;
  agent_log: Array<Record<string, unknown>>;
  live_inference: { last_model?: string; last_latency_ms?: number; in_flight?: number; completed?: number };
}

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
  cluster_id: string;
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

  /* SSE live state */
  const [live, setLive] = useState<StreamState | null>(null);

  /* Observatory REST state */
  const [clusters, setClusters] = useState<ObsCluster[] | null>(null);
  const [signals, setSignals] = useState<ObsSignal[] | null>(null);
  const [agents, setAgents] = useState<ObsAgent[] | null>(null);

  /* ----- SSE connection (throttled to 2s updates) -----  */
  const latestSSE = useRef<StreamState | null>(null);
  const sseTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const flushSSE = useCallback(() => {
    if (latestSSE.current) {
      setLive(latestSSE.current);
    }
  }, []);

  useEffect(() => {
    const es = new EventSource('/api/v1/stream');

    const handleEvent = (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data);
        if (d.metrics) latestSSE.current = d;
      } catch { /* ignore */ }
    };

    es.addEventListener('live', handleEvent);
    es.addEventListener('session', handleEvent);

    sseTimer.current = setInterval(flushSSE, 2000);

    return () => {
      es.close();
      if (sseTimer.current) clearInterval(sseTimer.current);
    };
  }, [flushSSE]);

  /* ----- REST polling for observatory data ----- */
  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      try {
        const [clRes, sigRes, agRes] = await Promise.all([
          fetch('/api/v1/observatory/clusters'),
          fetch('/api/v1/observatory/signals'),
          fetch('/api/v1/observatory/agents'),
        ]);
        if (cancelled) return;
        const clData = await clRes.json();
        const sigData = await sigRes.json();
        const agData = await agRes.json();

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
    const poll = setInterval(fetchAll, 30000);
    return () => { cancelled = true; clearInterval(poll); };
  }, []);

  /* ----- Derived values ----- */
  const m = live?.metrics;
  const clusterCount = m?.clusters_monitored ?? clusters?.length ?? 0;
  const signalsPerSec = m?.signals_per_second ?? 0;
  const compressionRatio = m?.compression_ratio;
  const inFlight = m?.inference_in_flight ?? 0;

  /* Funnel values */
  const rawSignals = m?.raw_signals ?? 0;
  const retained = m?.retained ?? 0;
  const findingsCount = m?.findings ?? 0;
  const reasoningTasks = m?.reasoning_tasks ?? 0;
  const inferenceCompleted = m?.inference_completed ?? 0;

  const funnelSteps = [
    { label: 'Raw', value: rawSignals, color: '#6A6E73' },
    { label: 'Retained', value: retained, color: '#0071C5' },
    { label: 'Findings', value: findingsCount, color: '#F0AB00' },
    { label: 'Tasks', value: Math.round(reasoningTasks), color: 'var(--brand-primary, #EE0000)' },
    { label: 'Inferences', value: inferenceCompleted, color: '#3E8635' },
  ];
  const funnelMax = Math.max(...funnelSteps.map((s) => s.value), 1);

  /* Model stats */
  const modelEntries = live?.model_stats ? Object.entries(live.model_stats) : [];

  /* Recent signals — last 10 */
  const recentSignals = (signals ?? []).slice(-10).reverse();

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
        {!live && (
          <div className="flex items-center gap-2 text-xs text-[#6A6E73]">
            <span className="w-2 h-2 rounded-full bg-[#6A6E73] animate-pulse" />
            Connecting to live stream...
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
      {/*  2. Signal Funnel — compact horizontal bar                    */}
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
      {/*  3. Nano-Agent Grid                                           */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Nano-Agent Grid
        </div>
        {agents === null ? (
          <div className="animate-pulse space-y-3">
            {[1,2].map(i => (
              <div key={i} className="bg-[#212121] rounded-lg h-16" />
            ))}
          </div>
        ) : agents.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">Pipeline initializing...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {agents.map((agent) => {
              const escRate =
                agent.evaluations > 0
                  ? (agent.escalations / agent.evaluations) * 100
                  : 0;
              const dotColor =
                escRate < 5
                  ? '#3E8635'
                  : escRate < 20
                    ? '#F0AB00'
                    : '#C9190B';

              return (
                <div
                  key={agent.name}
                  className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 flex items-center gap-3"
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: dotColor }}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-white truncate">
                      {agent.name}
                    </div>
                    <div className="text-xs text-[#6A6E73] mt-0.5">
                      {agent.evaluations.toLocaleString()} evals
                      <span className="mx-1">&middot;</span>
                      {escRate.toFixed(1)}% escalation
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  4. Active Models — horizontal strip                          */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Active Models
        </div>
        {modelEntries.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">{'—'}</div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {modelEntries.map(([model, stats]) => (
              <div
                key={model}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 min-w-[180px] flex-shrink-0"
              >
                <div className="text-xs font-mono text-[#6A6E73] truncate mb-1">
                  {model}
                </div>
                <div className="text-lg font-bold text-white tabular-nums">
                  {stats.calls}
                  <span className="text-[10px] text-[#6A6E73] ml-1">calls</span>
                </div>
                <div className="text-xs text-orange-400 tabular-nums mt-0.5">
                  {stats.avg_tps} tok/s &middot; {stats.avg_latency}ms
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  5. Recent Signals — last 10                                  */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Recent Signals
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
            {recentSignals.map((sig) => (
              <div
                key={sig.signal_id ?? `${sig.cluster_id}-${sig.timestamp}-${sig.signal_type}`}
                className="flex items-center gap-3 bg-[#1a1a1a] rounded-lg px-3 py-2 text-xs cursor-pointer hover:bg-[#252525]"
                onClick={() => navigate(`/cluster/${sig.cluster_id}`)}
              >
                {/* Severity badge */}
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                  style={{
                    color: sevColor(sig.severity),
                    backgroundColor: `${sevColor(sig.severity)}20`,
                  }}
                >
                  {sig.severity}
                </span>

                {/* Signal type */}
                <span className="text-white font-medium truncate max-w-[160px]">
                  {sig.signal_type}
                </span>

                {/* Namespace */}
                <span className="text-[#9CA3AF] truncate max-w-[120px]">
                  {sig.namespace}
                </span>

                {/* Cluster */}
                <span className="text-[#6A6E73] truncate max-w-[120px]">
                  {sig.cluster_id}
                </span>

                {/* Timestamp */}
                <span className="text-[#6A6E73] ml-auto whitespace-nowrap">
                  {sig.timestamp ? relativeTime(sig.timestamp) : '—'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  Cluster cards (clickable navigation)                         */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Cluster Detail
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
                <div className="text-sm font-semibold text-white mb-2 truncate">
                  {cl.cluster_id}
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="text-lg font-bold text-white tabular-nums">
                      {cl.total_pods}
                    </div>
                    <div className="text-[9px] text-[#6A6E73]">Pods</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold text-white tabular-nums">
                      {cl.total_nodes}
                    </div>
                    <div className="text-[9px] text-[#6A6E73]">Nodes</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold text-white tabular-nums">
                      {cl.total_events_warning}
                    </div>
                    <div className="text-[9px] text-[#6A6E73]">Warnings</div>
                  </div>
                </div>
                {cl.last_scan && (
                  <div className="text-[9px] text-[#6A6E73] mt-2">
                    Last scan: {relativeTime(cl.last_scan)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
