import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTimeRange } from '../components/TimeRangeContext';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface RawSignal {
  signal_id?: string;
  cluster_id?: string;
  namespace?: string;
  resource_kind?: string;
  signal_type?: string;
  severity?: string;
  timestamp?: string;
}

interface Inference {
  model?: string;
  task_type?: string;
  severity?: string;
  output?: string;
  prompt?: string;
  latency_ms?: number;
  timestamp?: string;
}

interface Remediation {
  cluster?: string;
  namespace?: string;
  command?: string;
  status?: string;
  output?: string;
  timestamp?: string;
}

interface Incident {
  namespace: string;
  signals: RawSignal[];
  highestSeverity: string;
  signalTypes: string[];
  latestTimestamp: string;
  remediation?: Remediation;
  inference?: Inference;
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

const SEV_ORDER: Record<string, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
  info: 0,
};

function sevColor(sev: string): string {
  return SEV_COLORS[sev?.toLowerCase()] ?? '#6A6E73';
}

function sevRank(sev: string): number {
  return SEV_ORDER[sev?.toLowerCase()] ?? 0;
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

/** Parse a signal that might be a dict or a plain string */
function normalizeSignal(raw: unknown): RawSignal | null {
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed === 'object' && parsed !== null) return parsed as RawSignal;
    } catch {
      /* not JSON — treat as opaque */
    }
    return { signal_type: raw, severity: 'info', namespace: 'unknown', timestamp: new Date().toISOString() };
  }
  if (typeof raw === 'object' && raw !== null) return raw as RawSignal;
  return null;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function Incidents() {
  const navigate = useNavigate();
  const { since } = useTimeRange();

  const [signals, setSignals] = useState<RawSignal[] | null>(null);
  const [inferences, setInferences] = useState<Inference[]>([]);
  const [remediations, setRemediations] = useState<Remediation[]>([]);
  const [expandedInference, setExpandedInference] = useState<string | null>(null);

  /* ----- Fetch data ----- */
  const fetchAll = useCallback(async () => {
    try {
      const [sigRes, infRes, remRes] = await Promise.all([
        fetch('/api/v1/observatory/signals'),
        fetch('/api/v1/observatory/history/inferences'),
        fetch('/api/v1/observatory/history/remediations'),
      ]);

      const sigData = await sigRes.json();
      const infData = await infRes.json();
      const remData = await remRes.json();

      if (sigData.signals && Array.isArray(sigData.signals)) {
        const parsed = sigData.signals.map(normalizeSignal).filter(Boolean) as RawSignal[];
        setSignals(parsed);
      } else {
        setSignals([]);
      }

      if (infData.inferences && Array.isArray(infData.inferences)) {
        setInferences(infData.inferences);
      }

      if (remData.remediations && Array.isArray(remData.remediations)) {
        setRemediations(remData.remediations);
      }
    } catch {
      /* network error — keep stale data */
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const poll = setInterval(fetchAll, 10000);
    return () => clearInterval(poll);
  }, [fetchAll]);

  /* ----- Filter data by time range ----- */
  const cutoff = since();
  const filteredSignals = (signals ?? []).filter(s => {
    const ts = s.timestamp;
    return ts ? new Date(ts).getTime() >= cutoff : true;
  });
  const filteredInferences = inferences.filter(inf => {
    const ts = inf.timestamp;
    return ts ? new Date(ts).getTime() >= cutoff : true;
  });
  const filteredRemediations = remediations.filter(rem => {
    const ts = rem.timestamp;
    return ts ? new Date(ts).getTime() >= cutoff : true;
  });

  /* ----- Build incidents (group signals by namespace) ----- */
  const incidents: Incident[] = (() => {
    if (!signals) return [];

    const groups: Record<string, RawSignal[]> = {};
    for (const sig of filteredSignals) {
      const ns = sig.namespace ?? 'unknown';
      if (!groups[ns]) groups[ns] = [];
      groups[ns].push(sig);
    }

    return Object.entries(groups)
      .map(([namespace, sigs]) => {
        const highestSev = sigs.reduce(
          (best, s) => (sevRank(s.severity ?? 'info') > sevRank(best) ? (s.severity ?? 'info') : best),
          'info',
        );
        const types = [...new Set(sigs.map((s) => s.signal_type ?? 'unknown'))];
        const latest = sigs.reduce(
          (best, s) => (!best || (s.timestamp && s.timestamp > best) ? s.timestamp ?? '' : best),
          '',
        );

        // Match remediation by namespace
        const rem = filteredRemediations.find((r) => r.namespace === namespace);
        // Match inference — look for namespace mention in prompt or output
        const inf = filteredInferences.find(
          (i) =>
            (i.prompt && i.prompt.includes(namespace)) ||
            (i.output && i.output.includes(namespace)),
        );

        return {
          namespace,
          signals: sigs,
          highestSeverity: highestSev,
          signalTypes: types,
          latestTimestamp: latest,
          remediation: rem,
          inference: inf,
        };
      })
      .sort((a, b) => {
        // Sort by severity desc, then by timestamp desc
        const sevDiff = sevRank(b.highestSeverity) - sevRank(a.highestSeverity);
        if (sevDiff !== 0) return sevDiff;
        return b.latestTimestamp.localeCompare(a.latestTimestamp);
      });
  })();

  /* ----- Stats ----- */
  const totalIncidents = incidents.length;

  const oneHourAgo = Date.now() - 60 * 60 * 1000;
  const openCount = incidents.filter((inc) => {
    const isHighSev = sevRank(inc.highestSeverity) >= 3; // high or critical
    const isRecent = inc.latestTimestamp && new Date(inc.latestTimestamp).getTime() > oneHourAgo;
    return isHighSev && isRecent;
  }).length;

  const resolvedCount = filteredRemediations.filter((r) => r.status === 'ok').length;

  const avgResponseTime = (() => {
    // Compute average gap between signal timestamp and remediation timestamp per namespace
    const gaps: number[] = [];
    for (const inc of incidents) {
      if (inc.remediation?.timestamp && inc.latestTimestamp) {
        const sigTime = new Date(inc.latestTimestamp).getTime();
        const remTime = new Date(inc.remediation.timestamp).getTime();
        const gap = remTime - sigTime;
        if (gap >= 0) gaps.push(gap);
      }
    }
    if (gaps.length === 0) return null;
    const avg = gaps.reduce((a, b) => a + b, 0) / gaps.length;
    const secs = Math.round(avg / 1000);
    if (secs < 60) return `${secs}s`;
    const mins = Math.round(secs / 60);
    return `${mins}m`;
  })();

  /* ----- Render ----- */
  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">

      {/* ============================================================ */}
      {/*  Header                                                       */}
      {/* ============================================================ */}
      <div>
        <h1
          className="text-3xl font-bold text-white mb-1"
          style={{ fontFamily: 'Red Hat Display, sans-serif' }}
        >
          Incidents
        </h1>
        <p className="text-sm text-[#6A6E73]">Correlated findings and remediation history</p>
      </div>

      {/* ============================================================ */}
      {/*  Stats Bar                                                    */}
      {/* ============================================================ */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Total Incidents', value: signals === null ? '...' : totalIncidents },
          { label: 'Open', value: signals === null ? '...' : openCount },
          { label: 'Resolved', value: resolvedCount },
          { label: 'Avg Response Time', value: avgResponseTime ?? '—' },
        ].map(({ label, value }) => (
          <div key={label} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
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
      {/*  Incident Timeline                                            */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-4">
          Incident Timeline
        </div>

        {signals === null ? (
          <div className="text-sm text-[#6A6E73]">Loading...</div>
        ) : incidents.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No incidents detected</div>
        ) : (
          <div className="space-y-3">
            {incidents.map((inc) => {
              const borderColor = sevColor(inc.highestSeverity);
              const isExpanded = expandedInference === inc.namespace;

              return (
                <div
                  key={inc.namespace}
                  className="border border-[#333] rounded-xl overflow-hidden"
                  style={{ borderLeftWidth: '4px', borderLeftColor: borderColor }}
                >
                  <div className="p-4">
                    {/* Top row: namespace + meta */}
                    <div className="flex items-center gap-3 flex-wrap">
                      {/* Namespace — clickable */}
                      <button
                        className="text-sm font-semibold text-white hover:underline text-left"
                        onClick={() => navigate(`/cluster/${inc.namespace}`)}
                      >
                        {inc.namespace}
                      </button>

                      {/* Severity badge */}
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                        style={{
                          color: sevColor(inc.highestSeverity),
                          backgroundColor: `${sevColor(inc.highestSeverity)}20`,
                        }}
                      >
                        {inc.highestSeverity}
                      </span>

                      {/* Signal count */}
                      <span className="text-xs text-[#6A6E73]">
                        {inc.signals.length} signal{inc.signals.length !== 1 ? 's' : ''}
                      </span>

                      {/* Timestamp */}
                      <span className="text-xs text-[#6A6E73] ml-auto whitespace-nowrap">
                        {inc.latestTimestamp ? relativeTime(inc.latestTimestamp) : '—'}
                      </span>
                    </div>

                    {/* Signal type badges */}
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {inc.signalTypes.map((t) => (
                        <span
                          key={t}
                          className="px-2 py-0.5 rounded text-[10px] font-medium bg-[#2e2e2e] text-[#9CA3AF]"
                        >
                          {t}
                        </span>
                      ))}
                    </div>

                    {/* Remediation inline */}
                    {inc.remediation && (
                      <div className="mt-3 flex items-center gap-2 text-xs">
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                          style={{
                            color: inc.remediation.status === 'ok' ? '#3E8635' : '#C9190B',
                            backgroundColor:
                              inc.remediation.status === 'ok' ? '#3E863520' : '#C9190B20',
                          }}
                        >
                          {inc.remediation.status}
                        </span>
                        <span className="text-[#9CA3AF] font-mono truncate">
                          {inc.remediation.command}
                        </span>
                      </div>
                    )}

                    {/* AI Analysis expandable */}
                    {inc.inference && (
                      <div className="mt-3">
                        <button
                          className="text-xs text-[#0071C5] hover:underline"
                          onClick={() =>
                            setExpandedInference(isExpanded ? null : inc.namespace)
                          }
                        >
                          {isExpanded ? '▼' : '▶'} AI Analysis
                        </button>
                        {isExpanded && (
                          <div className="mt-2 bg-[#1a1a1a] rounded-lg p-3 text-xs text-[#9CA3AF] whitespace-pre-wrap">
                            {inc.inference.output ?? 'No output'}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  Remediation History                                          */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Remediation History
        </div>

        {filteredRemediations.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No remediations executed</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="text-[#6A6E73] uppercase tracking-wider border-b border-[#333]">
                  <th className="py-2 pr-4">Timestamp</th>
                  <th className="py-2 pr-4">Namespace</th>
                  <th className="py-2 pr-4">Command</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2">Cluster</th>
                </tr>
              </thead>
              <tbody>
                {filteredRemediations.map((rem, i) => (
                  <tr
                    key={`${rem.namespace}-${rem.timestamp}-${i}`}
                    className="border-b border-[#2e2e2e] hover:bg-[#1a1a1a]"
                  >
                    <td className="py-2 pr-4 text-[#9CA3AF] whitespace-nowrap">
                      {rem.timestamp ? relativeTime(rem.timestamp) : '—'}
                    </td>
                    <td className="py-2 pr-4 text-white">{rem.namespace ?? '—'}</td>
                    <td className="py-2 pr-4 text-[#9CA3AF] font-mono truncate max-w-[260px]">
                      {rem.command ?? '—'}
                    </td>
                    <td className="py-2 pr-4">
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                        style={{
                          color: rem.status === 'ok' ? '#3E8635' : '#C9190B',
                          backgroundColor:
                            rem.status === 'ok' ? '#3E863520' : '#C9190B20',
                        }}
                      >
                        {rem.status ?? 'unknown'}
                      </span>
                    </td>
                    <td className="py-2 text-[#6A6E73]">{rem.cluster ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
