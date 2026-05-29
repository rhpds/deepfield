import { useState, useEffect } from 'react';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AgentStats {
  total_evaluated: number;
  escalated: number;
  kept: number;
  dropped: number;
  suppressed: number;
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

export default function SignalPipeline() {
  /* SSE live state */
  const [metrics, setMetrics] = useState<StreamMetrics>({});
  const [modelStats, setModelStats] = useState<Record<string, { calls: number }>>({});

  /* REST state */
  const [agents, setAgents] = useState<Record<string, AgentStats> | null>(null);
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);

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

  /* ----- REST polling for agent data ----- */
  useEffect(() => {
    let cancelled = false;

    async function fetchAgents() {
      try {
        const resp = await fetch('/api/v1/observatory/agents');
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

              return (
                <div
                  key={name}
                  className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: escalationColor(escRate) }}
                    />
                    <span className="text-sm font-semibold text-white truncate">{name}</span>
                    <span className="text-xs text-[#6A6E73] ml-auto">
                      {escRate.toFixed(1)}% esc
                    </span>
                  </div>
                  <div className="grid grid-cols-4 gap-2 text-center">
                    <div>
                      <div
                        className="text-lg font-bold text-white tabular-nums"
                        style={{ fontFamily: 'Red Hat Display, sans-serif' }}
                      >
                        {stats.total_evaluated.toLocaleString()}
                      </div>
                      <div className="text-[9px] text-[#6A6E73] uppercase">Evaluated</div>
                    </div>
                    <div>
                      <div
                        className="text-lg font-bold tabular-nums"
                        style={{ color: '#3E8635', fontFamily: 'Red Hat Display, sans-serif' }}
                      >
                        {stats.kept.toLocaleString()}
                      </div>
                      <div className="text-[9px] text-[#6A6E73] uppercase">Kept</div>
                    </div>
                    <div>
                      <div
                        className="text-lg font-bold tabular-nums"
                        style={{ color: '#6A6E73', fontFamily: 'Red Hat Display, sans-serif' }}
                      >
                        {stats.dropped.toLocaleString()}
                      </div>
                      <div className="text-[9px] text-[#6A6E73] uppercase">Dropped</div>
                    </div>
                    <div>
                      <div
                        className="text-lg font-bold tabular-nums"
                        style={{ color: '#F0AB00', fontFamily: 'Red Hat Display, sans-serif' }}
                      >
                        {stats.suppressed.toLocaleString()}
                      </div>
                      <div className="text-[9px] text-[#6A6E73] uppercase">Suppressed</div>
                    </div>
                  </div>
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
    </div>
  );
}
