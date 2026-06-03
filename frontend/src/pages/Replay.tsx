import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts';

interface RubricResult {
  score: 'healthy' | 'warning' | 'failing';
  checks: Array<[string, string]>;
}

interface ReplayProgress {
  replay_id: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  processed: number;
  errors: number;
  from_timestamp: string;
  to_timestamp: string;
  started_at: string | null;
  completed_at: string | null;
  results?: {
    agent_summary: Record<string, {
      total_evaluated: number;
      escalated: number;
      kept: number;
      suppressed: number;
      deduped: number;
      dropped: number;
      errors: number;
    }>;
    signal_count: number;
    finding_count: number;
    decision_count: number;
  };
  evaluation?: {
    cluster_id: string;
    timestamp: string;
    overall: 'healthy' | 'warning' | 'failing';
    rubrics: Record<string, RubricResult>;
  };
}

const SCORE_COLORS: Record<string, string> = { healthy: '#3E8635', warning: '#F0AB00', failing: '#C9190B' };
const STATUS_COLORS: Record<string, string> = { completed: '#3E8635', running: '#F0AB00', error: '#C9190B', pending: '#6A6E73' };
const RUBRIC_LABELS: Record<string, string> = {
  compression_quality: 'Compression',
  classification_accuracy: 'Classification',
  inference_value: 'Inference',
  signal_coverage: 'Coverage',
  tuning_safety: 'Safety',
};

function formatRange(from: string, to: string): string {
  try {
    const f = new Date(from);
    const t = new Date(to);
    const fmt = (d: Date) => d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    return `${fmt(f)} — ${fmt(t)}`;
  } catch { return `${from} — ${to}`; }
}

function duration(start: string | null, end: string | null): string {
  if (!start) return '';
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const secs = Math.round((e - s) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

export default function Replay() {
  const [replays, setReplays] = useState<ReplayProgress[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReplayProgress | null>(null);
  const [starting, setStarting] = useState(false);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  // Poll replay list
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch('/api/v1/workers');
        if (res.ok && !cancelled) {
          const data = await res.json();
          setReplays(data.replays || []);
        }
      } catch { /* */ }
    }
    load();
    const poll = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(poll); };
  }, []);

  // Poll selected replay detail
  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    let cancelled = false;
    let poll: ReturnType<typeof setInterval> | null = null;
    async function load() {
      try {
        const res = await fetch(`/api/v1/workers/replay/${selectedId}`);
        if (res.ok && !cancelled) {
          const data = await res.json();
          setDetail(data);
          if (poll && data.status !== 'running' && data.status !== 'pending') {
            clearInterval(poll);
            poll = null;
          }
        }
      } catch { /* */ }
    }
    load();
    poll = setInterval(load, 3000);
    return () => { cancelled = true; if (poll) clearInterval(poll); };
  }, [selectedId]);

  function setPreset(hours: number) {
    const now = new Date();
    const from = new Date(now.getTime() - hours * 3600_000);
    const toLocal = (d: Date) => {
      const off = d.getTimezoneOffset();
      return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
    };
    setFromDate(toLocal(from));
    setToDate(toLocal(now));
  }

  async function startReplay() {
    if (!fromDate || !toDate) return;
    setStarting(true);
    try {
      const res = await fetch('/api/v1/workers/replay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_timestamp: new Date(fromDate).toISOString(),
          to_timestamp: new Date(toDate).toISOString(),
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedId(data.replay_id);
      }
    } catch { /* */ }
    setStarting(false);
  }

  async function stopReplay(id: string) {
    await fetch(`/api/v1/workers/replay/${id}/stop`, { method: 'POST' });
  }

  const agentChartData = detail?.results?.agent_summary
    ? Object.entries(detail.results.agent_summary).map(([name, s]) => ({
        agent: name.length > 16 ? name.slice(0, 14) + '..' : name,
        kept: s.kept,
        dropped: s.dropped,
        suppressed: s.suppressed,
        deduped: s.deduped,
        escalated: s.escalated,
      }))
    : [];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>Event Replay</h1>
        <p className="text-sm text-[#6A6E73]">Re-process historical Kafka signals through the current pipeline — validate tuning changes without affecting production</p>
      </div>

      {/* Start replay form */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">Start New Replay</div>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="block text-[10px] text-[#6A6E73] uppercase mb-1">From</label>
            <input type="datetime-local" value={fromDate} onChange={e => setFromDate(e.target.value)}
              className="bg-[#1a1a1a] border border-[#333] rounded px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label className="block text-[10px] text-[#6A6E73] uppercase mb-1">To</label>
            <input type="datetime-local" value={toDate} onChange={e => setToDate(e.target.value)}
              className="bg-[#1a1a1a] border border-[#333] rounded px-3 py-2 text-sm text-white" />
          </div>
          <div className="flex gap-2">
            {[{ label: 'Last 1h', h: 1 }, { label: 'Last 6h', h: 6 }, { label: 'Last 24h', h: 24 }].map(p => (
              <button key={p.h} onClick={() => setPreset(p.h)}
                className="px-3 py-2 rounded text-xs font-bold bg-[#212121] text-[#6A6E73] hover:text-white hover:bg-[#333] border border-[#333]">
                {p.label}
              </button>
            ))}
          </div>
          <button onClick={startReplay} disabled={starting || !fromDate || !toDate}
            className="px-4 py-2 rounded text-sm font-bold bg-[#3E8635] text-white hover:bg-[#2d6427] disabled:opacity-50">
            {starting ? 'Starting...' : 'Start Replay'}
          </button>
        </div>
      </div>

      {/* Replay list */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">Replays ({replays.length})</div>
        {replays.length === 0 ? (
          <p className="text-sm text-[#6A6E73]">No replays — start one above to validate pipeline behavior against historical data</p>
        ) : (
          <div className="space-y-2">
            {replays.map((r: ReplayProgress) => (
              <div key={r.replay_id}
                onClick={() => setSelectedId(selectedId === r.replay_id ? null : r.replay_id)}
                className={`bg-[#212121] border rounded-lg p-3 cursor-pointer transition hover:border-[#555] ${
                  selectedId === r.replay_id ? 'border-[#0071C5]' : 'border-[#2e2e2e]'}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-bold px-2 py-0.5 rounded"
                      style={{ backgroundColor: `${STATUS_COLORS[r.status]}20`, color: STATUS_COLORS[r.status] }}>
                      {r.status.toUpperCase()}
                    </span>
                    <span className="text-xs font-mono text-[#6A6E73]">{r.replay_id.slice(0, 8)}</span>
                    <span className="text-xs text-[#6A6E73]">{formatRange(r.from_timestamp, r.to_timestamp)}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-xs text-white font-bold tabular-nums">{r.processed.toLocaleString()} msgs</span>
                    {r.errors > 0 && <span className="text-xs font-bold" style={{ color: '#C9190B' }}>{r.errors} errors</span>}
                    {r.started_at && <span className="text-xs text-[#6A6E73]">{duration(r.started_at, r.completed_at)}</span>}
                    {r.status === 'running' && (
                      <button onClick={e => { e.stopPropagation(); stopReplay(r.replay_id); }}
                        className="px-2 py-1 rounded text-xs font-bold bg-[#333] text-[#C9190B] hover:bg-[#C9190B] hover:text-white">
                        Stop
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Selected replay detail */}
      {detail && (
        <div className="space-y-4">
          {/* Summary metrics */}
          {detail.results && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: 'Signals', value: detail.results.signal_count, color: '#0071C5' },
                { label: 'Findings', value: detail.results.finding_count, color: '#F0AB00' },
                { label: 'Decisions', value: detail.results.decision_count, color: '#3E8635' },
                { label: 'Errors', value: detail.errors, color: detail.errors > 0 ? '#C9190B' : '#6A6E73' },
              ].map(m => (
                <div key={m.label} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold tabular-nums" style={{ color: m.color, fontFamily: 'Red Hat Display' }}>
                    {m.value.toLocaleString()}
                  </div>
                  <div className="text-xs text-[#6A6E73] uppercase mt-1">{m.label}</div>
                </div>
              ))}
            </div>
          )}

          {/* Rubric evaluation */}
          {detail.evaluation && (
            <div className="border border-[#333] rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">Replay Pipeline Evaluation</div>
                <span className="text-sm font-bold px-3 py-1 rounded-full"
                  style={{ backgroundColor: `${SCORE_COLORS[detail.evaluation.overall]}20`, color: SCORE_COLORS[detail.evaluation.overall] }}>
                  {detail.evaluation.overall.toUpperCase()}
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                {Object.entries(detail.evaluation.rubrics).map(([key, rubric]) => (
                  <div key={key} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3"
                    style={{ borderTop: `3px solid ${SCORE_COLORS[rubric.score]}` }}>
                    <div className="text-xs text-[#6A6E73] uppercase tracking-wider mb-1">{RUBRIC_LABELS[key] || key}</div>
                    <div className="text-sm font-bold mb-2" style={{ color: SCORE_COLORS[rubric.score] }}>
                      {rubric.score.toUpperCase()}
                    </div>
                    <div className="space-y-0.5">
                      {rubric.checks.map(([name, level]) => (
                        <div key={name} className="flex items-center gap-1.5 text-[10px]">
                          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SCORE_COLORS[level as keyof typeof SCORE_COLORS] || '#6A6E73' }} />
                          <span className="text-[#6A6E73]">{name.replace(/_/g, ' ')}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Agent summary table */}
          {detail.results?.agent_summary && Object.keys(detail.results.agent_summary).length > 0 && (
            <div className="border border-[#333] rounded-xl p-4">
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">Agent Summary</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[#6A6E73] uppercase text-[10px]">
                      <th className="text-left py-2 pr-4">Agent</th>
                      <th className="text-right py-2 px-2">Evaluated</th>
                      <th className="text-right py-2 px-2">Kept</th>
                      <th className="text-right py-2 px-2">Dropped</th>
                      <th className="text-right py-2 px-2">Deduped</th>
                      <th className="text-right py-2 px-2">Suppressed</th>
                      <th className="text-right py-2 px-2">Escalated</th>
                      <th className="text-right py-2 px-2">Errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(detail.results.agent_summary).map(([name, s]) => (
                      <tr key={name} className="border-t border-[#2e2e2e]">
                        <td className="py-2 pr-4 text-white font-mono">{name}</td>
                        <td className="text-right py-2 px-2 tabular-nums text-[#6A6E73]">{s.total_evaluated.toLocaleString()}</td>
                        <td className="text-right py-2 px-2 tabular-nums" style={{ color: '#3E8635' }}>{s.kept.toLocaleString()}</td>
                        <td className="text-right py-2 px-2 tabular-nums text-[#6A6E73]">{s.dropped.toLocaleString()}</td>
                        <td className="text-right py-2 px-2 tabular-nums" style={{ color: '#0071C5' }}>{s.deduped.toLocaleString()}</td>
                        <td className="text-right py-2 px-2 tabular-nums" style={{ color: '#F0AB00' }}>{s.suppressed.toLocaleString()}</td>
                        <td className="text-right py-2 px-2 tabular-nums" style={{ color: s.escalated > 0 ? '#C9190B' : '#6A6E73' }}>{s.escalated.toLocaleString()}</td>
                        <td className="text-right py-2 px-2 tabular-nums" style={{ color: s.errors > 0 ? '#C9190B' : '#6A6E73' }}>{s.errors}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Agent outcomes chart */}
          {agentChartData.length > 0 && (
            <div className="border border-[#333] rounded-xl p-4">
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">Agent Decision Breakdown</div>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={agentChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="agent" tick={{ fontSize: 10, fill: '#6A6E73' }} stroke="#333" />
                  <YAxis tick={{ fontSize: 10, fill: '#6A6E73' }} stroke="#333" />
                  <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333', borderRadius: 6, fontSize: 11 }} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#6A6E73' }} />
                  <Bar dataKey="kept" stackId="a" fill="#3E8635" name="Kept" />
                  <Bar dataKey="deduped" stackId="a" fill="#0071C5" name="Deduped" />
                  <Bar dataKey="suppressed" stackId="a" fill="#F0AB00" name="Suppressed" />
                  <Bar dataKey="dropped" stackId="a" fill="#6A6E73" name="Dropped" />
                  <Bar dataKey="escalated" stackId="a" fill="#C9190B" name="Escalated" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Running state */}
          {detail.status === 'running' && (
            <div className="border border-[#F0AB00] rounded-xl p-4 flex items-center gap-3">
              <div className="w-2 h-2 rounded-full bg-[#F0AB00] animate-pulse" />
              <span className="text-sm text-[#F0AB00] font-bold">Processing...</span>
              <span className="text-sm text-white tabular-nums">{detail.processed.toLocaleString()} messages</span>
              {detail.errors > 0 && <span className="text-sm text-[#C9190B]">{detail.errors} errors</span>}
              <span className="text-xs text-[#6A6E73]">{duration(detail.started_at, null)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
