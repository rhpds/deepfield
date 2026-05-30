import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTimeRange } from '../components/TimeRangeContext';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ClusterData {
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

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
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

export default function ClusterDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { since, sinceISO } = useTimeRange();

  const [cluster, setCluster] = useState<ClusterData | null>(null);
  const [signals, setSignals] = useState<ObsSignal[] | null>(null);
  const [loading, setLoading] = useState(true);

  /* ----- REST polling ----- */
  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const [clRes, sigRes] = await Promise.all([
          fetch('/api/v1/observatory/clusters'),
          fetch(`/api/v1/observatory/signals?since=${encodeURIComponent(sinceISO())}`),
        ]);
        if (cancelled) return;

        const clData = await clRes.json();
        const sigData = await sigRes.json();

        if (clData.clusters) {
          const cl = clData.clusters;
          if (Array.isArray(cl)) {
            const found = cl.find((c: Record<string, unknown>) => c.cluster_id === id);
            if (found) setCluster(found);
          } else if (cl[id!]) {
            setCluster(cl[id!]);
          }
        }

        if (sigData.signals) {
          const all: ObsSignal[] = Array.isArray(sigData.signals) ? sigData.signals : [];
          setSignals(all.filter((s) => s.cluster === id));
        }

        setLoading(false);
      } catch {
        setLoading(false);
      }
    }

    fetchData();
    const poll = setInterval(fetchData, 5000);
    return () => { cancelled = true; clearInterval(poll); };
  }, [id]);

  /* ----- Filter signals by time range ----- */
  const cutoff = since();
  const filteredSignals = (signals ?? []).filter(s => {
    const ts = s.timestamp;
    return ts ? new Date(ts).getTime() >= cutoff : true;
  });

  /* ----- Derived ----- */
  const nsEntries = cluster ? Object.entries(cluster.namespaces ?? {}) : [];
  const maxNsCount = Math.max(...nsEntries.map(([, c]) => c), 1);
  const clusterSignals = filteredSignals.slice(-15).reverse();

  /* Pod status bar */
  const totalPods = cluster?.total_pods ?? 0;
  const podSegments = cluster
    ? [
        { label: 'Running', count: cluster.pods_running, color: '#3E8635' },
        { label: 'Pending', count: cluster.pods_pending, color: '#F0AB00' },
        { label: 'Failed', count: cluster.pods_failed, color: '#C9190B' },
        { label: 'CrashLoop', count: cluster.pods_crashloop, color: '#C9190B' },
      ]
    : [];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">

      {/* ============================================================ */}
      {/*  Header + back link                                           */}
      {/* ============================================================ */}
      <div>
        <button
          onClick={() => navigate('/')}
          className="text-xs text-[#6A6E73] hover:text-white transition-colors mb-2 flex items-center gap-1"
        >
          <span>&larr;</span> Back to Fleet Overview
        </button>
        <h1
          className="text-3xl font-bold text-white mb-1"
          style={{ fontFamily: 'Red Hat Display, sans-serif' }}
        >
          {id}
        </h1>
        <p className="text-sm text-[#6A6E73]">
          {cluster?.last_scan
            ? `Last scan: ${relativeTime(cluster.last_scan)}`
            : 'Cluster health and signal detail'}
        </p>
      </div>

      {loading && !cluster ? (
        <div className="text-sm text-[#6A6E73]">Loading cluster data...</div>
      ) : !cluster ? (
        <div className="text-sm text-[#6A6E73]">
          No data found for cluster <span className="text-white font-mono">{id}</span>
        </div>
      ) : (
        <>
          {/* ============================================================ */}
          {/*  Health Summary — 4 metric cards                              */}
          {/* ============================================================ */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Total Pods', value: cluster.total_pods, color: 'text-white' },
              { label: 'Pods Running', value: cluster.pods_running, color: 'text-[#3E8635]' },
              { label: 'Pods Failed', value: cluster.pods_failed, color: 'text-[#C9190B]' },
              { label: 'Nodes Ready', value: `${cluster.nodes_ready} / ${cluster.total_nodes}`, color: 'text-white' },
            ].map(({ label, value, color }) => (
              <div
                key={label}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4"
              >
                <div
                  className={`text-2xl font-bold tabular-nums ${color}`}
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
          {/*  Pod Status Breakdown — horizontal stacked bar                */}
          {/* ============================================================ */}
          <div className="border border-[#333] rounded-xl p-4">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
              Pod Status Breakdown
            </div>
            {totalPods === 0 ? (
              <div className="text-sm text-[#6A6E73]">No pods</div>
            ) : (
              <>
                <div className="flex h-6 rounded overflow-hidden">
                  {podSegments.map((seg) => {
                    const pct = totalPods > 0 ? (seg.count / totalPods) * 100 : 0;
                    if (pct === 0) return null;
                    return (
                      <div
                        key={seg.label}
                        className="h-full transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: seg.color,
                          animation: seg.label === 'CrashLoop' && seg.count > 0
                            ? 'pulse 2s infinite'
                            : undefined,
                        }}
                        title={`${seg.label}: ${seg.count}`}
                      />
                    );
                  })}
                </div>
                <div className="flex gap-4 mt-2">
                  {podSegments.map((seg) => (
                    <div key={seg.label} className="flex items-center gap-1.5 text-xs">
                      <span
                        className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                        style={{ backgroundColor: seg.color }}
                      />
                      <span className="text-[#6A6E73]">{seg.label}</span>
                      <span className="text-white font-bold tabular-nums">{seg.count}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* ============================================================ */}
          {/*  Namespace Breakdown                                          */}
          {/* ============================================================ */}
          <div className="border border-[#333] rounded-xl p-4">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
              Namespace Breakdown
            </div>
            {nsEntries.length === 0 ? (
              <div className="text-sm text-[#6A6E73]">No namespace data</div>
            ) : (
              <div className="space-y-1">
                {nsEntries
                  .sort(([, a], [, b]) => b - a)
                  .map(([ns, count]) => {
                    const pct = maxNsCount > 0 ? (count / maxNsCount) * 100 : 0;
                    return (
                      <div
                        key={ns}
                        className="flex items-center gap-3 bg-[#1a1a1a] rounded-lg px-3 py-2 hover:bg-[#252525] transition-colors cursor-default"
                      >
                        <span className="text-xs text-white font-medium truncate min-w-[140px] max-w-[200px]">
                          {ns}
                        </span>
                        <div className="flex-1 h-3 bg-[#2e2e2e] rounded overflow-hidden">
                          <div
                            className="h-full rounded"
                            style={{
                              width: `${pct}%`,
                              backgroundColor: '#0071C5',
                            }}
                          />
                        </div>
                        <span className="text-xs text-[#6A6E73] tabular-nums w-10 text-right">
                          {count}
                        </span>
                      </div>
                    );
                  })}
              </div>
            )}
          </div>

          {/* ============================================================ */}
          {/*  Node Health (placeholder)                                    */}
          {/* ============================================================ */}
          <div className="border border-[#333] rounded-xl p-4">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
              Node Health
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div
                  className="text-2xl font-bold text-white tabular-nums"
                  style={{ fontFamily: 'Red Hat Display, sans-serif' }}
                >
                  {cluster.total_nodes}
                </div>
                <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
                  Total Nodes
                </div>
              </div>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div
                  className="text-2xl font-bold text-[#3E8635] tabular-nums"
                  style={{ fontFamily: 'Red Hat Display, sans-serif' }}
                >
                  {cluster.nodes_ready}
                </div>
                <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
                  Nodes Ready
                </div>
              </div>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div
                  className="text-2xl font-bold text-[#F0AB00] tabular-nums"
                  style={{ fontFamily: 'Red Hat Display, sans-serif' }}
                >
                  {cluster.nodes_pressure}
                </div>
                <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
                  Nodes Under Pressure
                </div>
              </div>
            </div>
          </div>

          {/* ============================================================ */}
          {/*  Recent Signals for this cluster                              */}
          {/* ============================================================ */}
          <div className="border border-[#333] rounded-xl p-4">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
              Recent Signals
            </div>
            {signals === null ? (
              <div className="text-sm text-[#6A6E73]">Loading...</div>
            ) : clusterSignals.length === 0 ? (
              <div className="text-sm text-[#6A6E73]">No recent signals for this cluster</div>
            ) : (
              <div className="space-y-1">
                {clusterSignals.map((sig, i) => (
                  <div
                    key={sig.signal_id ?? `${sig.namespace}-${sig.timestamp}-${i}`}
                    className="flex items-center gap-3 bg-[#1a1a1a] rounded-lg px-3 py-2 text-xs"
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
                    <span className="text-white font-medium truncate max-w-[180px]">
                      {sig.signal_type}
                    </span>

                    {/* Namespace */}
                    <span className="text-[#9CA3AF] truncate max-w-[140px]">
                      {sig.namespace}
                    </span>

                    {/* Resource kind */}
                    <span className="text-[#6A6E73] truncate max-w-[100px]">
                      {sig.resource_kind}
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
        </>
      )}
    </div>
  );
}
