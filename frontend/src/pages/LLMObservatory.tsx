import { useState, useEffect } from 'react';
import { useTimeRange } from '../components/TimeRangeContext';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ModelStats {
  calls: number;
  avg_latency: number;
  avg_tps: number;
}

interface Inference {
  model: string;
  task_type: string;
  severity: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  ttft_ms: number;
  tokens_per_second: number;
  output: string;
  prompt: string;
  error: string;
  timestamp: string;
  /* legacy fields the backend may also send */
  _ts?: string;
  tier?: string;
}

interface RemediationResult {
  status: string;
  command: string;
  output: string;
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

function hwLane(model: string): 'gaudi3' | 'xeon6' {
  const lower = model.toLowerCase();
  if (lower.includes('cpu') || lower.includes('granite') || lower.includes('phi3_mini') || lower.includes('qwen25')) {
    return 'xeon6';
  }
  return 'gaudi3';
}

function tryParseJSON(text: string): Record<string, unknown> | null {
  try {
    const cleaned = text.replace(/^```json\s*/, '').replace(/```\s*$/, '').trim();
    return JSON.parse(cleaned);
  } catch { return null; }
}

/* ------------------------------------------------------------------ */
/*  Remediation Panel (preserved from original)                        */
/* ------------------------------------------------------------------ */

function RemediationPanel({ output, finding }: { output: string; finding: Record<string, unknown> }) {
  const [results, setResults] = useState<Record<string, RemediationResult>>({});
  const [executing, setExecuting] = useState<string | null>(null);

  const parsed = tryParseJSON(output);
  if (!parsed?.remediation) return null;

  const rem = parsed.remediation as Record<string, unknown>;
  const steps = (rem.steps ?? []) as string[];
  const commands = (rem.commands ?? []) as string[];
  const priority = String(rem.priority ?? '');
  const risk = String(rem.risk ?? 'medium');
  const note = String(rem.note ?? '');

  const executeCommand = async (cmd: string, idx: number) => {
    const key = `cmd-${idx}`;
    setExecuting(key);

    const parts = cmd.replace(/^oc\s+/, '').split(/\s+/);
    let command = parts[0];
    let resourceKind = 'Pod';
    let resourceName = '';
    let namespace = '';
    const extraArgs: Record<string, unknown> = {};

    const kindMap: Record<string, string> = {
      pod: 'Pod', pods: 'Pod', deployment: 'Deployment', deployments: 'Deployment',
      deploy: 'Deployment', job: 'Job', jobs: 'Job', service: 'Service', svc: 'Service',
      node: 'Node', nodes: 'Node', event: 'Event', events: 'Event',
    };

    for (let i = 0; i < parts.length; i++) {
      if ((parts[i] === '-n' || parts[i] === '--namespace') && parts[i + 1]) { namespace = parts[i + 1]; i++; continue; }
      if (parts[i] === '--tail' && parts[i + 1]) { extraArgs.tailLines = parts[i + 1]; i++; continue; }
      if (parts[i] === '-c' && parts[i + 1]) { extraArgs.container = parts[i + 1]; i++; continue; }
      if (parts[i] === '--replicas' && parts[i + 1]) { extraArgs.replicas = Number(parts[i + 1]); i++; continue; }
      const mapped = kindMap[parts[i]?.toLowerCase()];
      if (mapped) {
        resourceKind = mapped;
        if (parts[i + 1] && !parts[i + 1].startsWith('-')) { resourceName = parts[i + 1]; i++; }
      }
    }

    if (command === 'delete' && resourceKind === 'Pod') command = 'delete_pod';
    if (command === 'rollout' && parts[1] === 'restart') { command = 'rollout_restart'; resourceKind = 'Deployment'; if (!resourceName && parts[2] && !parts[2].startsWith('-')) resourceName = parts[2]; }
    if (command === 'scale') resourceKind = 'Deployment';
    if (command === 'logs') resourceKind = 'Pod';

    const promptStr = String((finding as Record<string, unknown>).prompt ?? '');
    const evidencePart = promptStr.split('Evidence:')[1] ?? '{}';
    const evidenceJson = tryParseJSON(evidencePart.trim());
    if (!namespace && evidenceJson?.namespaces) namespace = (evidenceJson.namespaces as string[])[0] ?? '';
    const cluster = (evidenceJson?.clusters as string[] ?? [])[0] ?? 'infra01';

    if (!resourceName && parsed?.affected_resources) {
      const resources = parsed.affected_resources as string[];
      if (resources.length > 0) resourceName = resources[0];
    }

    const debugInfo = `Parsed: command=${command} kind=${resourceKind} name=${resourceName} ns=${namespace} cluster=${cluster}`;

    try {
      const resp = await fetch('/api/v1/remediation/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cluster, namespace, command,
          resource_kind: resourceKind, resource_name: resourceName || 'unknown',
          args: Object.keys(extraArgs).length > 0 ? extraArgs : undefined,
        }),
      });
      const data = await resp.json();
      if (data.detail) {
        setResults(prev => ({ ...prev, [key]: { status: 'error', command, output: `${data.detail}\n\n${debugInfo}` } }));
      } else {
        setResults(prev => ({ ...prev, [key]: data }));
      }
    } catch (e) {
      setResults(prev => ({ ...prev, [key]: { status: 'error', command, output: `${String(e)}\n\n${debugInfo}` } }));
    }
    setExecuting(null);
  };

  const priorityColor = priority === 'immediate' ? 'text-red-400' : priority === 'soon' ? 'text-orange-400' : 'text-yellow-400';
  const riskColor = risk === 'high' ? 'bg-red-900/50 text-red-300' : risk === 'medium' ? 'bg-orange-900/50 text-orange-300' : 'bg-green-900/50 text-green-300';

  return (
    <div className="mt-2 border border-[#333] rounded p-3 bg-[#0a0a0a]">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] text-[#6A6E73] uppercase font-semibold">Remediation</span>
        <span className={`text-[10px] font-bold ${priorityColor}`}>{priority}</span>
        <span className={`text-[10px] px-1 rounded ${riskColor}`}>risk: {risk}</span>
      </div>

      {steps.length > 0 && (
        <div className="mb-2">
          <div className="text-[10px] text-[#6A6E73] uppercase mb-1">Steps</div>
          <ol className="list-decimal list-inside text-xs text-[#9CA3AF] space-y-0.5">
            {steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        </div>
      )}

      {commands.length > 0 && (
        <div>
          <div className="text-[10px] text-[#6A6E73] uppercase mb-1">Commands (click to execute)</div>
          <div className="space-y-1">
            {commands.map((cmd, i) => {
              const key = `cmd-${i}`;
              const result = results[key];
              return (
                <div key={i}>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-[#1a1a1a] rounded px-2 py-1 text-xs text-[#e0e0e0] font-mono">{cmd}</code>
                    <button
                      onClick={(e) => { e.stopPropagation(); executeCommand(cmd, i); }}
                      disabled={executing === key}
                      className={`px-3 py-1 rounded text-[10px] font-medium ${executing === key ? 'bg-[#333] text-[#6A6E73]' : 'text-white hover:opacity-90'}`}
                      style={executing !== key ? { backgroundColor: 'var(--brand-primary)' } : {}}>
                      {executing === key ? 'Running...' : 'Execute'}
                    </button>
                  </div>
                  {result && (
                    <pre className={`mt-1 rounded p-2 text-[11px] whitespace-pre-wrap max-h-40 overflow-y-auto font-mono ${result.status === 'ok' ? 'bg-green-900/20 text-green-300' : 'bg-red-900/20 text-red-300'}`}>
                      {result.output}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {note && <div className="mt-2 text-[10px] text-yellow-400">Note: {note}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function LLMObservatory() {
  const { range } = useTimeRange();

  /* SSE live state */
  const [sseModels, setSseModels] = useState<Record<string, ModelStats>>({});

  /* REST state */
  const [inferences, setInferences] = useState<Inference[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);

  /* ----- SSE connection ----- */
  useEffect(() => {
    const es = new EventSource('/api/v1/stream');

    const handler = (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data);
        if (d.model_stats) setSseModels(d.model_stats);
      } catch { /* ignore malformed */ }
    };

    es.addEventListener('live', handler);
    es.addEventListener('session', handler);

    return () => es.close();
  }, []);

  /* ----- REST polling for inference history ----- */
  useEffect(() => {
    let cancelled = false;

    async function fetchInferences() {
      try {
        const resp = await fetch(`/api/v1/observatory/history/inferences?window=${range.key}`);
        if (cancelled) return;
        const data = await resp.json();
        if (data.inferences) {
          setInferences(data.inferences);
        } else if (data.recent_inferences) {
          /* fallback: legacy endpoint shape */
          setInferences(data.recent_inferences);
        }
      } catch {
        /* Also try legacy endpoint */
        try {
          const resp = await fetch('/api/v1/observatory/llm');
          if (cancelled) return;
          const data = await resp.json();
          if (data.recent_inferences) setInferences(data.recent_inferences);
          /* Merge model data from REST if SSE hasn't provided any */
          if (data.models && Object.keys(sseModels).length === 0) {
            const mapped: Record<string, ModelStats> = {};
            for (const [name, stats] of Object.entries(data.models)) {
              const s = stats as Record<string, number>;
              mapped[name] = { calls: s.total_calls ?? 0, avg_latency: s.avg_latency ?? 0, avg_tps: s.avg_tps ?? 0 };
            }
            setSseModels(mapped);
          }
        } catch { /* */ }
      }
    }

    fetchInferences();
    const poll = setInterval(fetchInferences, 3000);
    return () => { cancelled = true; clearInterval(poll); };
  }, [sseModels, range.key]);

  /* ----- Derived: model entries ----- */
  const modelEntries = Object.entries(sseModels);

  /* ----- Derived: hardware lane aggregates ----- */
  const laneTotals = { gaudi3: { calls: 0, latencySum: 0, count: 0 }, xeon6: { calls: 0, latencySum: 0, count: 0 } };
  for (const [name, stats] of modelEntries) {
    const lane = hwLane(name);
    laneTotals[lane].calls += stats.calls;
    laneTotals[lane].latencySum += stats.avg_latency * stats.calls;
    laneTotals[lane].count += stats.calls;
  }
  const gaudiAvgLatency = laneTotals.gaudi3.count > 0 ? Math.round(laneTotals.gaudi3.latencySum / laneTotals.gaudi3.count) : 0;
  const xeonAvgLatency = laneTotals.xeon6.count > 0 ? Math.round(laneTotals.xeon6.latencySum / laneTotals.xeon6.count) : 0;

  /* ----- Recent inferences, newest first (backend already filters by window) ----- */
  const recentInferences = inferences.slice().reverse();

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
          LLM Observatory
        </h1>
        <p className="text-sm text-[#6A6E73]">Model performance, inference history, cost tracking</p>
      </div>

      {/* ============================================================ */}
      {/*  Model Cards — horizontal row                                 */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Active Models
        </div>
        {modelEntries.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No model data yet</div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {modelEntries.map(([name, stats]) => {
              const lane = hwLane(name);
              const isGpu = lane === 'gaudi3';
              return (
                <div
                  key={name}
                  className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 min-w-[200px] flex-shrink-0"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-mono text-white truncate">
                      {name.split('_').slice(0, 2).join('_')}
                    </span>
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ml-auto"
                      style={{
                        color: isGpu ? '#C9190B' : '#0071C5',
                        backgroundColor: isGpu ? '#C9190B20' : '#0071C520',
                      }}
                    >
                      {isGpu ? 'Gaudi 3' : 'Xeon 6'}
                    </span>
                  </div>
                  <div
                    className="text-2xl font-bold text-white tabular-nums"
                    style={{ fontFamily: 'Red Hat Display, sans-serif' }}
                  >
                    {stats.calls.toLocaleString()}
                  </div>
                  <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-0.5">
                    Total Calls
                  </div>
                  <div className="flex gap-3 mt-2 text-xs tabular-nums">
                    <span className="text-[#6A6E73]">{stats.avg_latency}ms avg</span>
                    <span className="text-orange-400">{stats.avg_tps} tok/s</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ============================================================ */}
      {/*  Hardware Lane Split                                          */}
      {/* ============================================================ */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <span
              className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
              style={{ color: '#C9190B', backgroundColor: '#C9190B20' }}
            >
              GPU
            </span>
            <span className="text-sm font-semibold text-white">Gaudi 3</span>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div
                className="text-2xl font-bold text-white tabular-nums"
                style={{ fontFamily: 'Red Hat Display, sans-serif' }}
              >
                {laneTotals.gaudi3.calls.toLocaleString()}
              </div>
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
                Total Calls
              </div>
            </div>
            <div>
              <div
                className="text-2xl font-bold text-white tabular-nums"
                style={{ fontFamily: 'Red Hat Display, sans-serif' }}
              >
                {gaudiAvgLatency}ms
              </div>
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
                Avg Latency
              </div>
            </div>
          </div>
        </div>

        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <span
              className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
              style={{ color: '#0071C5', backgroundColor: '#0071C520' }}
            >
              CPU
            </span>
            <span className="text-sm font-semibold text-white">Xeon 6</span>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div
                className="text-2xl font-bold text-white tabular-nums"
                style={{ fontFamily: 'Red Hat Display, sans-serif' }}
              >
                {laneTotals.xeon6.calls.toLocaleString()}
              </div>
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
                Total Calls
              </div>
            </div>
            <div>
              <div
                className="text-2xl font-bold text-white tabular-nums"
                style={{ fontFamily: 'Red Hat Display, sans-serif' }}
              >
                {xeonAvgLatency}ms
              </div>
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
                Avg Latency
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ============================================================ */}
      {/*  Recent Inferences                                            */}
      {/* ============================================================ */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Recent Inferences ({inferences.length})
        </div>
        {recentInferences.length === 0 ? (
          <div className="text-sm text-[#6A6E73]">No inferences yet. Start a session to see inference logs.</div>
        ) : (
          <div className="space-y-1 max-h-[700px] overflow-y-auto">
            {recentInferences.map((inf, i) => {
              const isExpanded = expanded === i;
              const lane = hwLane(String(inf.model ?? ''));
              const isGpu = lane === 'gaudi3';
              const borderColor = isGpu ? '#EC7A08' : '#0071C5';
              const outputStr = String(inf.output ?? '');
              const parsed = tryParseJSON(outputStr);
              const hasRemediation = parsed?.remediation != null;
              const sev = String(inf.severity ?? '');
              const ts = inf.timestamp ?? inf._ts;

              return (
                <div
                  key={i}
                  className="bg-[#1a1a1a] rounded border-l-2 cursor-pointer hover:bg-[#252525] transition-colors"
                  style={{ borderColor }}
                  onClick={() => setExpanded(isExpanded ? null : i)}
                >
                  <div className="p-2 flex items-center gap-2 text-xs">
                    {/* Model badge */}
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                      style={{
                        color: isGpu ? '#EC7A08' : '#0071C5',
                        backgroundColor: isGpu ? '#EC7A0820' : '#0071C520',
                      }}
                    >
                      {String(inf.model ?? '').split('_').slice(0, 2).join('_')}
                    </span>

                    {/* Task type */}
                    <span className="text-white font-medium">{String(inf.task_type ?? '')}</span>

                    {/* Severity badge */}
                    {sev && (
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                        style={{
                          color: sevColor(sev),
                          backgroundColor: `${sevColor(sev)}20`,
                        }}
                      >
                        {sev}
                      </span>
                    )}

                    {hasRemediation && (
                      <span className="text-[10px] px-1 rounded bg-blue-900/50 text-blue-300">
                        has remediation
                      </span>
                    )}

                    {/* Latency + tokens on right */}
                    <span className="text-[#6A6E73] ml-auto whitespace-nowrap">
                      {ts ? new Date(String(ts)).toLocaleTimeString() : ''}
                    </span>
                    <span className="text-[#6A6E73] tabular-nums">{String(inf.latency_ms ?? '')}ms</span>
                    <span className="text-orange-400 tabular-nums">{String(inf.tokens_out ?? '')}tok</span>
                    <span className="text-[#6A6E73]">{isExpanded ? '▲' : '▼'}</span>
                  </div>

                  {isExpanded && (
                    <div className="px-2 pb-2 space-y-2">
                      {/* Prompt */}
                      <div>
                        <div className="text-[10px] text-[#6A6E73] uppercase mb-0.5">Prompt</div>
                        <div className="bg-[#252525] rounded p-2 text-xs text-[#9CA3AF] whitespace-pre-wrap max-h-32 overflow-y-auto font-mono">
                          {String(inf.prompt ?? '')}
                        </div>
                      </div>

                      {/* Output */}
                      <div>
                        <div className="text-[10px] text-[#6A6E73] uppercase mb-0.5">Output</div>
                        {parsed ? (
                          <div className="bg-[#252525] rounded p-2 text-xs whitespace-pre-wrap max-h-64 overflow-y-auto font-mono">
                            {parsed.root_cause ? (
                              <div className="mb-1">
                                <span className="text-[#6A6E73]">Root Cause:</span>{' '}
                                <span className="text-white">{String(parsed.root_cause)}</span>
                              </div>
                            ) : null}
                            {parsed.category ? (
                              <div className="mb-1">
                                <span className="text-[#6A6E73]">Category:</span>{' '}
                                <span className="text-yellow-400">{String(parsed.category)}</span>
                              </div>
                            ) : null}
                            {parsed.confidence != null ? (
                              <div className="mb-1">
                                <span className="text-[#6A6E73]">Confidence:</span>{' '}
                                <span className="text-orange-400">{String(parsed.confidence)}</span>
                              </div>
                            ) : null}
                            {parsed.evidence_chain ? (
                              <div className="mb-1">
                                <span className="text-[#6A6E73]">Evidence:</span>{' '}
                                <span className="text-[#9CA3AF]">{(parsed.evidence_chain as string[]).join(' → ')}</span>
                              </div>
                            ) : null}
                            {parsed.affected_resources ? (
                              <div className="mb-1">
                                <span className="text-[#6A6E73]">Affected:</span>{' '}
                                <span className="text-white">{(parsed.affected_resources as string[]).join(', ')}</span>
                              </div>
                            ) : null}
                            {!parsed.root_cause && <span className="text-white">{JSON.stringify(parsed, null, 2)}</span>}
                          </div>
                        ) : (
                          <div className="bg-[#252525] rounded p-2 text-xs text-white whitespace-pre-wrap max-h-48 overflow-y-auto font-mono">
                            {outputStr}
                          </div>
                        )}
                      </div>

                      {hasRemediation && <RemediationPanel output={outputStr} finding={inf as unknown as Record<string, unknown>} />}
                      {inf.error && <div className="text-xs text-red-400">Error: {String(inf.error)}</div>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
