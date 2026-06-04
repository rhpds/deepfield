import { useState, useEffect } from 'react';
import { useTimeRange } from '../components/TimeRangeContext';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AgentStats {
  total_evaluated: number;
  escalated: number;
  kept: number;
  dropped: number;
  suppressed: number;
  deduped: number;
}

interface AgentDecision {
  filter_name: string;
  outcome: string;
  reason: string;
  signal_id: string;
  timestamp?: string;
}

interface StreamMetrics {
  raw_signals?: number;
  reasoning_tasks?: number;
  inference_completed?: number;
  findings?: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function escalationColor(rate: number): string {
  if (rate < 5) return '#3E8635';
  if (rate < 20) return '#F0AB00';
  return '#C9190B';
}

const OUTCOME_STYLES: Record<string, { color: string; bg: string }> = {
  keep:     { color: '#3E8635', bg: '#3E863520' },
  drop:     { color: '#6A6E73', bg: '#6A6E7320' },
  escalate: { color: '#C9190B', bg: '#C9190B20' },
  suppress: { color: '#F0AB00', bg: '#F0AB0020' },
};

function outcomeStyle(outcome: string) {
  return OUTCOME_STYLES[outcome?.toLowerCase()] ?? { color: '#6A6E73', bg: '#6A6E7320' };
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface WorkerStat {
  worker: string;
  topic: string;
  group_id: string;
  messages_processed: number;
  errors: number;
  alive: boolean;
  uptime_s: number;
}

interface WorkersData {
  workers: WorkerStat[];
  total_processed: number;
  total_errors: number;
  status: string;
  replays?: Array<Record<string, unknown>>;
}

export default function SignalPipeline() {
  const { range } = useTimeRange();

  /* SSE live state */
  const [metrics, setMetrics] = useState<StreamMetrics>({});
  const [modelStats, setModelStats] = useState<Record<string, { calls: number }>>({});
  const [workers, setWorkers] = useState<WorkersData | null>(null);

  /* REST state */
  const [agents, setAgents] = useState<Record<string, AgentStats> | null>(null);
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  /* ----- SSE connection ----- */
  useEffect(() => {
    const es = new EventSource('/api/v1/stream');

    const handler = (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data);
        if (d.metrics) {
          setMetrics({
            raw_signals: d.metrics.raw_signals,
            reasoning_tasks: d.metrics.reasoning_tasks,
            inference_completed: d.metrics.inference_completed,
            findings: d.metrics.findings,
          });
        }
        if (d.model_stats) setModelStats(d.model_stats);
      } catch { /* ignore malformed */ }
    };

    es.addEventListener('live', handler);
    es.addEventListener('session', handler);

    return () => es.close();
  }, []);

  /* ----- REST polling for Kafka workers ----- */
  useEffect(() => {
    async function fetchWorkers() {
      try {
        const resp = await fetch('/api/v1/workers');
        if (resp.ok) setWorkers(await resp.json());
      } catch { /* */ }
    }
    fetchWorkers();
    const poll = setInterval(fetchWorkers, 5000);
    return () => clearInterval(poll);
  }, []);

  /* ----- REST polling for agent data ----- */
  useEffect(() => {
    let cancelled = false;

    async function fetchAgents() {
      try {
        const resp = await fetch(`/api/v1/observatory/agents?window=${range.key}`);
        if (cancelled) return;
        const data = await resp.json();
        if (data.agents) {
          if (typeof data.agents === 'object' && !Array.isArray(data.agents)) {
            setAgents(data.agents);
          } else if (Array.isArray(data.agents)) {
            const map: Record<string, AgentStats> = {};
            for (const a of data.agents) {
              map[a.name] = {
                total_evaluated: a.total_evaluated ?? a.evaluations ?? 0,
                escalated: a.escalated ?? a.escalations ?? 0,
                kept: a.kept ?? 0,
                dropped: a.dropped ?? 0,
                suppressed: a.suppressed ?? a.suppressions ?? 0,
                deduped: a.deduped ?? 0,
              };
            }
            setAgents(map);
          }
        }
        if (data.recent_decisions) {
          setDecisions(data.recent_decisions);
        }
      } catch { /* */ }
    }

    fetchAgents();
    const poll = setInterval(fetchAgents, 5000);
    return () => { cancelled = true; clearInterval(poll); };
  }, []);

  /* ----- Derived ----- */
  const agentEntries = agents ? Object.entries(agents) : [];
  const rawSignals = metrics.raw_signals ?? 0;
  const findings = metrics.findings ?? 0;
  const reasoningTasks = metrics.reasoning_tasks ?? 0;
  const inferenceCompleted = metrics.inference_completed ?? 0;
  const modelsUsed = Object.keys(modelStats).length;

  /* ----- Flow stages ----- */
  const flowStages = [
    { label: 'Raw Signals', value: rawSignals.toLocaleString() },
    { label: 'Nano-Agent Filters', value: `${agentEntries.length} agents` },
    { label: 'Correlation Engine', value: `${findings.toLocaleString()} findings` },
    { label: 'LLM Inference', value: `${Math.round(reasoningTasks)} tasks, ${modelsUsed} model${modelsUsed !== 1 ? 's' : ''}` },
    { label: 'Insights', value: `${inferenceCompleted.toLocaleString()} completed` },
  ];

  const recentDecisions = decisions.slice(-20).reverse();

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
          Signal Pipeline
        </h1>
        <p className="text-sm text-[#6A6E73]">Nano-agent filtering and correlation</p>
      </div>

      {/* ============================================================ */}
      {/*  Live Agent Flow Diagram                                      */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Live Agent Flow
        </div>
        <div className="flex flex-col items-center gap-0">
          {flowStages.map((stage, i) => (
            <div key={stage.label} className="flex flex-col items-center w-full max-w-md">
              {/* Stage box */}
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 w-full text-center">
                <div className="text-sm font-semibold text-white">{stage.label}</div>
                <div
                  className="text-lg font-bold text-white tabular-nums mt-0.5"
                  style={{ fontFamily: 'Red Hat Display, sans-serif' }}
                >
                  {stage.value}
                </div>
              </div>
              {/* Arrow connector (CSS, not SVG) */}
              {i < flowStages.length - 1 && (
                <div className="flex flex-col items-center py-1">
                  <div className="w-px h-4 bg-[#6A6E73]" />
                  <div
                    className="w-0 h-0"
                    style={{
                      borderLeft: '5px solid transparent',
                      borderRight: '5px solid transparent',
                      borderTop: '6px solid #6A6E73',
                    }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ============================================================ */}
      {/*  Agent Detail Cards — 2-column grid                           */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Agent Detail
        </div>
        {agents === null ? (
          <div className="text-sm text-[#6A6E73]">Loading...</div>
        ) : agentEntries.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No agents registered</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {agentEntries.map(([name, stats]) => {
              const escRate = stats.total_evaluated > 0
                ? (stats.escalated / stats.total_evaluated) * 100
                : 0;

              const isSelected = selectedAgent === name;
              const agentDecisions = decisions.filter(d => d.filter_name === name);

              return (
                <div key={name}>
                  <div
                    className={`bg-[#212121] border rounded-lg p-4 cursor-pointer transition-colors ${isSelected ? 'border-white/30' : 'border-[#2e2e2e] hover:border-[#555]'}`}
                    onClick={() => setSelectedAgent(isSelected ? null : name)}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: escalationColor(escRate) }}
                      />
                      <span className="text-sm font-semibold text-white truncate">{name}</span>
                      <span className="text-xs text-[#6A6E73] ml-auto">
                        {escRate.toFixed(1)}% esc
                        {(stats.deduped || 0) > 0 && ` · ${((stats.deduped / stats.total_evaluated) * 100).toFixed(0)}% dedup`}
                      </span>
                    </div>
                    {/* Decision outcome bar */}
                    {stats.total_evaluated > 0 && (
                      <div className="h-2 flex rounded-full overflow-hidden gap-px mb-3">
                        {[
                          { v: stats.kept, color: '#3E8635' },
                          { v: stats.deduped || 0, color: '#0071C5' },
                          { v: stats.suppressed, color: '#F0AB00' },
                          { v: stats.dropped, color: '#6A6E73' },
                          { v: stats.escalated, color: '#EE0000' },
                        ].map(({ v, color }, i) => {
                          if (!v) return null;
                          return <div key={i} style={{ width: `${(v / stats.total_evaluated) * 100}%`, backgroundColor: color, minWidth: '2px' }} />;
                        })}
                      </div>
                    )}
                    <div className="grid grid-cols-5 gap-2 text-center">
                      {[
                        { v: stats.total_evaluated, l: 'Evaluated', c: 'text-white' },
                        { v: stats.escalated, l: 'Escalated', c: 'text-[#EE0000]' },
                        { v: stats.kept, l: 'Kept', c: 'text-[#3E8635]' },
                        { v: stats.dropped, l: 'Dropped', c: 'text-[#6A6E73]' },
                        { v: stats.suppressed, l: 'Suppressed', c: 'text-[#F0AB00]' },
                      ].map(({ v, l, c }) => (
                        <div key={l}>
                          <div className={`text-lg font-bold tabular-nums ${c}`} style={{ fontFamily: 'Red Hat Display' }}>{v.toLocaleString()}</div>
                          <div className="text-[9px] text-[#6A6E73] uppercase">{l}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {isSelected && (
                    <div className="mt-2 border border-[#333] rounded-lg p-4 bg-[#1a1a1a] space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">{name} — Decision Log</span>
                        <span className="text-xs text-[#6A6E73]">{agentDecisions.length} decisions</span>
                      </div>

                      {/* Outcome breakdown */}
                      <div className="flex gap-3">
                        {(['keep', 'escalate', 'drop', 'suppress', 'dedupe', 'enrich'] as const).map(outcome => {
                          const count = agentDecisions.filter(d => d.outcome === outcome).length;
                          if (count === 0) return null;
                          const style = outcomeStyle(outcome);
                          return (
                            <div key={outcome} className="flex items-center gap-1.5">
                              <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded" style={{ color: style.color, backgroundColor: style.bg }}>{outcome}</span>
                              <span className="text-xs text-white tabular-nums">{count}</span>
                            </div>
                          );
                        })}
                      </div>

                      {/* Decision list */}
                      {agentDecisions.length === 0 ? (
                        <p className="text-xs text-[#6A6E73]">No recent decisions from this agent</p>
                      ) : (
                        <div className="space-y-1 max-h-[300px] overflow-y-auto">
                          {agentDecisions.map((d, i) => {
                            const style = outcomeStyle(d.outcome);
                            return (
                              <div key={`${d.signal_id}-${i}`} className="flex items-center gap-3 bg-[#212121] rounded px-3 py-2 text-xs">
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase" style={{ color: style.color, backgroundColor: style.bg }}>{d.outcome}</span>
                                <span className="text-[#9CA3AF] truncate flex-1">{d.reason}</span>
                                <span className="text-[#6A6E73] font-mono text-[10px]">{d.signal_id}</span>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  Recent Decisions Feed                                        */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Recent Decisions
        </div>
        {recentDecisions.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No recent decisions</div>
        ) : (
          <div className="space-y-1">
            {recentDecisions.map((d, i) => {
              const style = outcomeStyle(d.outcome);
              return (
                <div
                  key={`${d.signal_id}-${i}`}
                  className="flex items-center gap-3 bg-[#1a1a1a] rounded-lg px-3 py-2 text-xs"
                >
                  {/* Filter name */}
                  <span className="text-white font-medium truncate min-w-[120px] max-w-[160px]">
                    {d.filter_name}
                  </span>

                  {/* Outcome badge */}
                  <span
                    className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                    style={{ color: style.color, backgroundColor: style.bg }}
                  >
                    {d.outcome}
                  </span>

                  {/* Reason */}
                  <span className="text-[#9CA3AF] truncate flex-1">
                    {d.reason}
                  </span>

                  {/* Signal ID */}
                  <span className="text-[#6A6E73] font-mono text-[10px] whitespace-nowrap ml-auto">
                    {d.signal_id}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Kafka Workers */}
      {workers && workers.workers.length > 0 && (
        <div className="border border-[#333] rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
              Kafka Consumer Workers
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-[#6A6E73]">{workers.total_processed.toLocaleString()} processed</span>
              {workers.total_errors > 0 && <span className="text-[#C9190B] font-bold">{workers.total_errors} errors</span>}
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {workers.workers.map(w => (
              <div key={w.worker} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4"
                style={{ borderTop: `3px solid ${w.alive ? '#3E8635' : '#C9190B'}` }}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-white font-semibold">{w.worker.replace('Worker', '')}</span>
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${w.alive ? 'bg-[#3E8635]/20 text-[#3E8635]' : 'bg-[#C9190B]/20 text-[#C9190B]'}`}>
                    {w.alive ? 'ALIVE' : 'DOWN'}
                  </span>
                </div>
                <div className="text-xs text-[#6A6E73] font-mono mb-2">{w.topic}</div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="text-lg font-bold text-white tabular-nums">{w.messages_processed.toLocaleString()}</div>
                    <div className="text-[10px] text-[#6A6E73]">msgs</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold tabular-nums" style={{ color: w.errors > 0 ? '#C9190B' : '#3E8635' }}>{w.errors}</div>
                    <div className="text-[10px] text-[#6A6E73]">errors</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold text-white tabular-nums">{Math.round(w.uptime_s / 60)}m</div>
                    <div className="text-[10px] text-[#6A6E73]">uptime</div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Active Replays */}
          {workers.replays && workers.replays.length > 0 && (
            <div className="mt-4 border-t border-[#333] pt-3">
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">
                Replays ({workers.replays.length})
              </div>
              <div className="space-y-2">
                {workers.replays.map((r, i) => (
                  <div key={i} className="bg-[#1a1a1a] rounded px-3 py-2 flex items-center gap-3 text-xs">
                    <span className="font-bold px-2 py-0.5 rounded"
                      style={{ backgroundColor: `${r.status === 'completed' ? '#3E8635' : r.status === 'running' ? '#F0AB00' : '#C9190B'}20`,
                               color: r.status === 'completed' ? '#3E8635' : r.status === 'running' ? '#F0AB00' : '#C9190B' }}>
                      {String(r.status).toUpperCase()}
                    </span>
                    <span className="text-[#6A6E73] font-mono">{String(r.replay_id).slice(0, 8)}</span>
                    <span className="text-white">{r.processed as number} msgs</span>
                    {r.errors as number > 0 && <span className="text-[#C9190B]">{r.errors as number} errors</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
