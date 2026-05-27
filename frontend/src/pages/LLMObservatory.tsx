import { useState, useEffect } from 'react';

interface ModelStats {
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  avg_latency: number;
  avg_tps: number;
  errors: number;
  task_types: Record<string, number>;
}

interface RemediationResult {
  status: string;
  command: string;
  output: string;
}

function tryParseJSON(text: string): Record<string, unknown> | null {
  try {
    const cleaned = text.replace(/^```json\s*/, '').replace(/```\s*$/, '').trim();
    return JSON.parse(cleaned);
  } catch { return null; }
}

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

    // Fall back to finding context for namespace/cluster
    const promptStr = String((finding as Record<string, unknown>).prompt ?? '');
    const evidencePart = promptStr.split('Evidence:')[1] ?? '{}';
    const evidenceJson = tryParseJSON(evidencePart.trim());
    if (!namespace && evidenceJson?.namespaces) namespace = (evidenceJson.namespaces as string[])[0] ?? '';
    const cluster = (evidenceJson?.clusters as string[] ?? [])[0] ?? 'infra01';

    // If still no resource name, try to get from affected_resources in the parsed output
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

export default function LLMObservatory() {
  const [models, setModels] = useState<Record<string, ModelStats>>({});
  const [inferences, setInferences] = useState<Array<Record<string, unknown>>>([]);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const resp = await fetch('/api/v1/observatory/llm');
        const data = await resp.json();
        if (data.models) setModels(data.models);
        if (data.recent_inferences) setInferences(data.recent_inferences);
      } catch { /* */ }
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  const totalCalls = Object.values(models).reduce((s, m) => s + m.total_calls, 0);
  const totalTokensOut = Object.values(models).reduce((s, m) => s + m.total_tokens_out, 0);

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white" style={{ fontFamily: 'Red Hat Display' }}>LLM Observatory</h1>
        <span className="text-xs text-[#6A6E73]">Model fleet: Gaudi 3 ▲ + Xeon 6 ▼</span>
      </div>

      {/* Aggregate */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-white tabular-nums">{totalCalls.toLocaleString()}</div>
          <div className="text-[10px] text-[#6A6E73]">Total Calls</div>
        </div>
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-orange-400 tabular-nums">{totalTokensOut.toLocaleString()}</div>
          <div className="text-[10px] text-[#6A6E73]">Tokens Generated</div>
        </div>
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-white tabular-nums">{Object.keys(models).length}</div>
          <div className="text-[10px] text-[#6A6E73]">Active Models</div>
        </div>
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold tabular-nums" style={{ color: 'var(--brand-primary)' }}>
            {Object.values(models).reduce((s, m) => s + m.errors, 0)}
          </div>
          <div className="text-[10px] text-[#6A6E73]">Errors</div>
        </div>
      </div>

      {/* Model fleet */}
      <div className="rounded-xl p-4 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Model Fleet</span>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
          {Object.entries(models).map(([name, stats]) => {
            const isMicro = name.includes('cpu') || name.includes('granite') || name.includes('phi3_mini') || name.includes('qwen25');
            return (
              <div key={name} className={`bg-[#1a1a1a] rounded p-3 border-l-2 ${isMicro ? 'border-[#0071C5]' : 'border-orange-400'}`}>
                <div className="flex items-center gap-1">
                  <span className={`text-[10px] font-bold ${isMicro ? 'text-[#0071C5]' : 'text-orange-400'}`}>{isMicro ? '▼' : '▲'}</span>
                  <span className="text-xs font-mono text-[#6A6E73] truncate">{name.split('_').slice(0, 2).join('_')}</span>
                </div>
                <div className="text-xl font-bold text-white mt-1">{stats.total_calls}</div>
                <div className="text-[10px] text-[#6A6E73]">calls</div>
                <div className="text-xs mt-1 space-y-0.5">
                  <div className="text-orange-400">{stats.avg_tps} tok/s</div>
                  <div className="text-[#6A6E73]">{stats.avg_latency}ms avg</div>
                  <div className="text-[#6A6E73]">{stats.total_tokens_out.toLocaleString()} tokens</div>
                  {stats.errors > 0 ? <div className="text-red-400">{stats.errors} errors</div> : null}
                </div>
                {Object.keys(stats.task_types).length > 0 ? (
                  <div className="mt-1 text-[10px] text-[#6A6E73]">
                    {Object.entries(stats.task_types).map(([t, c]) => `${t}:${c}`).join(' ')}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {/* Inference Log */}
      <div className="rounded-xl p-4 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Inference Log ({inferences.length})</span>
        <div className="mt-2 space-y-1 max-h-[700px] overflow-y-auto">
          {inferences.slice().reverse().map((inf, i) => {
            const isExpanded = expanded === i;
            const isMicro = String(inf.tier ?? '') === 'micro';
            const borderColor = isMicro ? '#0071C5' : '#EC7A08';
            const outputStr = String(inf.output ?? '');
            const parsed = tryParseJSON(outputStr);
            const hasRemediation = parsed?.remediation != null;

            return (
              <div key={i} className="bg-[#1a1a1a] rounded border-l-2 cursor-pointer hover:bg-[#252525]"
                style={{ borderColor }} onClick={() => setExpanded(isExpanded ? null : i)}>
                <div className="p-2 flex items-center gap-2 text-xs">
                  <span className={`font-bold text-[10px] ${isMicro ? 'text-[#0071C5]' : 'text-orange-400'}`}>
                    {isMicro ? '▼' : '▲'}
                  </span>
                  <span className="font-mono text-[#6A6E73]">{String(inf.model ?? '').split('_').slice(0, 2).join('_')}</span>
                  <span className="text-white">{String(inf.task_type ?? '')}</span>
                  {inf.severity ? <span className={`text-[10px] px-1 rounded ${String(inf.severity) === 'critical' ? 'bg-red-900/50 text-red-300' : String(inf.severity) === 'high' ? 'bg-orange-900/50 text-orange-300' : 'bg-yellow-900/50 text-yellow-300'}`}>{String(inf.severity)}</span> : null}
                  {hasRemediation && <span className="text-[10px] px-1 rounded bg-blue-900/50 text-blue-300">has remediation</span>}
                  <span className="text-[#6A6E73] ml-auto">{inf._ts ? new Date(String(inf._ts)).toLocaleTimeString() : ''}</span>
                  <span className="text-[#6A6E73]">{String(inf.latency_ms ?? '')}ms</span>
                  <span className="text-orange-400">{String(inf.tokens_out ?? '')}tok</span>
                  <span className="text-[#6A6E73]">{isExpanded ? '▲' : '▼'}</span>
                </div>
                {isExpanded ? (
                  <div className="px-2 pb-2 space-y-2">
                    <div>
                      <div className="text-[10px] text-[#6A6E73] uppercase mb-0.5">Prompt</div>
                      <div className="bg-[#252525] rounded p-2 text-xs text-[#9CA3AF] whitespace-pre-wrap max-h-32 overflow-y-auto font-mono">{String(inf.prompt ?? '')}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-[#6A6E73] uppercase mb-0.5">Output</div>
                      {parsed ? (
                        <div className="bg-[#252525] rounded p-2 text-xs whitespace-pre-wrap max-h-64 overflow-y-auto font-mono">
                          {parsed.root_cause && <div className="mb-1"><span className="text-[#6A6E73]">Root Cause:</span> <span className="text-white">{String(parsed.root_cause)}</span></div>}
                          {parsed.category && <div className="mb-1"><span className="text-[#6A6E73]">Category:</span> <span className="text-yellow-400">{String(parsed.category)}</span></div>}
                          {parsed.confidence != null && <div className="mb-1"><span className="text-[#6A6E73]">Confidence:</span> <span className="text-orange-400">{String(parsed.confidence)}</span></div>}
                          {parsed.evidence_chain && <div className="mb-1"><span className="text-[#6A6E73]">Evidence:</span> <span className="text-[#9CA3AF]">{(parsed.evidence_chain as string[]).join(' → ')}</span></div>}
                          {parsed.affected_resources && <div className="mb-1"><span className="text-[#6A6E73]">Affected:</span> <span className="text-white">{(parsed.affected_resources as string[]).join(', ')}</span></div>}
                          {!parsed.root_cause && <span className="text-white">{JSON.stringify(parsed, null, 2)}</span>}
                        </div>
                      ) : (
                        <div className="bg-[#252525] rounded p-2 text-xs text-white whitespace-pre-wrap max-h-48 overflow-y-auto">{outputStr}</div>
                      )}
                    </div>
                    {hasRemediation && <RemediationPanel output={outputStr} finding={inf} />}
                    {inf.error ? <div className="text-xs text-red-400">Error: {String(inf.error)}</div> : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {!Object.keys(models).length && (
        <div className="text-center py-12 text-[#6A6E73]">
          <p className="text-lg mb-2">No LLM data yet</p>
          <p className="text-sm">Start a session to see model performance and inference logs.</p>
        </div>
      )}
    </div>
  );
}
