import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTimeRange } from '../components/TimeRangeContext';

interface Incident {
  id: string;
  namespace: string;
  cluster_id: string;
  failure_class: string | null;
  severity: string;
  status: string;
  signal_count: number;
  first_seen: string;
  last_seen: string;
  summary: string | null;
  rca_output: string | null;
  classification: { failure_class: string; confidence: number; model: string } | null;
  remediation_options: Array<{ action: string; command: string | null; risk: string; source: string }>;
  evidence: {
    signals: Array<{ signal_id: string; type: string; namespace: string; resource: string; severity: string; ts: string }>;
    classifications: Array<{ failure_class: string; confidence: number; model: string; ts: string }>;
    inferences: Array<{ type: string; model: string; output_summary: string; ts: string }>;
    remediations_suggested: Array<{ action: string; command: string | null; risk: string; source: string }>;
  };
}

const SEV_COLORS: Record<string, string> = { critical: '#C9190B', high: '#EE0000', medium: '#F0AB00', low: '#0071C5', info: '#6A6E73' };
const SEV_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
const RISK_COLORS: Record<string, string> = { low: '#3E8635', medium: '#F0AB00', high: '#C9190B' };
const ECOSYSTEM_NS = new Set(['deepfield', 'stargate', 'partner-ai-launchpad', 'platform-dashboard', 'intel-rh-demo']);

function relativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 0) return 'now';
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function tryParseJSON(text: string): Record<string, unknown> | null {
  try {
    // Strip markdown fences, think blocks, and prose preamble
    let cleaned = text
      .replace(/^```json\s*/m, '').replace(/```\s*$/m, '')
      .replace(/<think>[\s\S]*?<\/think>/g, '')
      .trim();
    const start = cleaned.indexOf('{');
    if (start >= 0) {
      const jsonStr = cleaned.substring(start);
      try { return JSON.parse(jsonStr); } catch { /* truncated — try fixing */ }
      // Fix truncated JSON by closing open braces/brackets
      let fixed = jsonStr;
      const opens = (fixed.match(/{/g) || []).length;
      const closes = (fixed.match(/}/g) || []).length;
      for (let i = 0; i < opens - closes; i++) fixed += '}';
      const openB = (fixed.match(/\[/g) || []).length;
      const closeB = (fixed.match(/]/g) || []).length;
      for (let i = 0; i < openB - closeB; i++) fixed += ']';
      fixed = fixed.replace(/,\s*([}\]])/g, '$1');
      try { return JSON.parse(fixed); } catch { /* give up */ }
    }
  } catch { /* */ }
  return null;
}

interface RemediationModal {
  command: string;
  namespace: string;
  cluster: string;
  parsed: Record<string, unknown> | null;
  status: 'parsing' | 'ready' | 'blocked' | 'executing' | 'done' | 'error';
  result: string | null;
}

export default function Incidents() {
  const navigate = useNavigate();
  const { range } = useTimeRange();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [modal, setModal] = useState<RemediationModal | null>(null);

  async function handleExecuteClick(command: string, namespace: string, cluster: string) {
    setModal({ command, namespace, cluster, parsed: null, status: 'parsing', result: null });
    try {
      const resp = await fetch('/api/v1/remediation/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command_string: command, namespace, cluster }),
      });
      const data = await resp.json();
      if (!data.valid) {
        setModal(m => m ? { ...m, status: 'blocked', parsed: data, result: data.reason } : null);
      } else if (data.blocked) {
        setModal(m => m ? { ...m, status: 'blocked', parsed: data, result: data.block_reason } : null);
      } else {
        setModal(m => m ? { ...m, status: 'ready', parsed: data } : null);
      }
    } catch {
      setModal(m => m ? { ...m, status: 'error', result: 'Failed to parse command' } : null);
    }
  }

  async function confirmExecute() {
    if (!modal?.parsed) return;
    const p = modal.parsed as Record<string, string>;
    setModal(m => m ? { ...m, status: 'executing' } : null);
    try {
      const resp = await fetch('/api/v1/remediation/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cluster: p.cluster, namespace: p.namespace,
          command: p.command, resource_kind: p.resource_kind,
          resource_name: p.resource_name,
        }),
      });
      const data = await resp.json();
      setModal(m => m ? { ...m, status: 'done', result: data.output || data.error || JSON.stringify(data) } : null);
    } catch (e) {
      setModal(m => m ? { ...m, status: 'error', result: 'Execution failed' } : null);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function fetchIncidents() {
      try {
        const resp = await fetch(`/api/v1/incidents?window=${range.key}`);
        if (!cancelled) {
          const data = await resp.json();
          setIncidents(data.incidents || []);
          setLoading(false);
        }
      } catch { setLoading(false); }
    }
    fetchIncidents();
    const poll = setInterval(fetchIncidents, 10000);
    return () => { cancelled = true; clearInterval(poll); };
  }, [range.key]);

  const openCount = incidents.filter(i => i.status === 'open' && SEV_RANK[i.severity] >= 3).length;
  const withRCA = incidents.filter(i => i.rca_output).length;
  const withRemediation = incidents.filter(i => i.remediation_options.length > 0).length;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>Incidents</h1>
        <p className="text-sm text-[#6A6E73]">Evidence-driven incidents with classification and remediation</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        {[
          { label: 'Total', value: incidents.length },
          { label: 'Open', value: incidents.filter(i => i.status === 'open').length, color: '#EE0000' },
          { label: 'High/Critical', value: openCount, color: openCount > 0 ? '#C9190B' : '#3E8635' },
          { label: 'With RCA', value: withRCA, color: withRCA > 0 ? '#3E8635' : '#6A6E73' },
          { label: 'With Remediation', value: withRemediation, color: withRemediation > 0 ? '#3E8635' : '#6A6E73' },
          { label: 'Namespaces', value: new Set(incidents.map(i => i.namespace)).size },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 text-center">
            <div className="text-2xl font-bold tabular-nums" style={{ color: color || '#fff', fontFamily: 'Red Hat Display' }}>{value}</div>
            <div className="text-[10px] text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
          </div>
        ))}
      </div>

      {/* Incident Timeline */}
      {incidents.length > 0 && (() => {
        const now = Date.now();
        const windowMs = { '5m': 5, '15m': 15, '1h': 60, '6h': 360, '24h': 1440, '7d': 10080 }[range.key] ?? 60;
        const windowStart = now - windowMs * 60000;
        const timelineSlots = 24;
        const slotMs = (windowMs * 60000) / timelineSlots;

        const slots = Array.from({ length: timelineSlots }, (_, i) => {
          const slotStart = windowStart + i * slotMs;
          const slotEnd = slotStart + slotMs;
          let worst = 0;
          let count = 0;
          for (const inc of incidents) {
            const first = new Date(inc.first_seen).getTime();
            const last = new Date(inc.last_seen).getTime();
            if (last >= slotStart && first <= slotEnd) {
              count++;
              worst = Math.max(worst, SEV_RANK[inc.severity] ?? 0);
            }
          }
          return { worst, count, time: new Date(slotStart) };
        });

        const worstColor = (rank: number) =>
          rank >= 4 ? '#C9190B' : rank >= 3 ? '#EE0000' : rank >= 2 ? '#F0AB00' : rank >= 1 ? '#0071C5' : '#2e2e2e';

        // Failure class distribution
        const classCounts: Record<string, number> = {};
        for (const inc of incidents) {
          const fc = inc.failure_class || 'unclassified';
          classCounts[fc] = (classCounts[fc] || 0) + 1;
        }
        const classSorted = Object.entries(classCounts).sort(([, a], [, b]) => b - a);
        const CLASS_COLORS: Record<string, string> = {
          config_error: '#F0AB00', image_issue: '#0071C5', oom_kill: '#C9190B',
          resource_exhaustion: '#EE0000', probe_failure: '#F0AB00', job_failure: '#6A6E73',
          scheduling_issue: '#0071C5', dependency_failure: '#EE0000', network_issue: '#0071C5',
          unclassified: '#333', unknown: '#333',
        };

        return (
          <div className="border border-[#333] rounded-xl p-4">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">Incident Timeline</div>
            <div className="flex items-end gap-px h-10 mb-1">
              {slots.map((s, i) => (
                <div key={i} className="flex-1 flex flex-col items-center justify-end h-full"
                  title={`${s.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}: ${s.count} incident${s.count !== 1 ? 's' : ''}`}>
                  <div className="w-full rounded-t" style={{
                    height: s.count > 0 ? `${Math.max(20, Math.min(100, s.count * 25))}%` : '4px',
                    backgroundColor: worstColor(s.worst),
                  }} />
                </div>
              ))}
            </div>
            <div className="flex justify-between text-[8px] text-[#6A6E73] mb-3">
              <span>{slots[0]?.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              <span>{slots[Math.floor(timelineSlots / 2)]?.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              <span>now</span>
            </div>
            {/* Failure class breakdown */}
            <div className="flex flex-wrap gap-3">
              {classSorted.map(([fc, count]) => (
                <div key={fc} className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CLASS_COLORS[fc] || '#6A6E73' }} />
                  <span className="text-[10px] text-[#6A6E73]">{fc.replace(/_/g, ' ')}</span>
                  <span className="text-[10px] text-white font-bold tabular-nums">{count}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Incident list */}
      {loading ? (
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map(i => <div key={i} className="bg-[#212121] rounded-xl h-32" />)}
        </div>
      ) : incidents.length === 0 ? (
        <div className="text-center py-12 text-[#6A6E73]">No incidents in this time window</div>
      ) : (
        <div className="space-y-4">
          {incidents.map(inc => {
            const isExpanded = expanded === inc.id;
            const sevColor = SEV_COLORS[inc.severity] || '#6A6E73';
            const rca = inc.rca_output ? tryParseJSON(inc.rca_output) : null;
            const canExecute = ECOSYSTEM_NS.has(inc.namespace);

            return (
              <div key={inc.id} className="border rounded-xl overflow-hidden"
                style={{ borderColor: isExpanded ? sevColor : '#333', borderLeftWidth: '4px', borderLeftColor: sevColor }}>

                {/* Header — always visible, rich preview */}
                <div className="p-5 cursor-pointer hover:bg-[#1a1a1a] transition-colors"
                  onClick={() => setExpanded(isExpanded ? null : inc.id)}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-bold px-2 py-1 rounded" style={{ backgroundColor: `${sevColor}20`, color: sevColor }}>
                        {inc.severity.toUpperCase()}
                      </span>
                      <span className="text-white font-semibold cursor-pointer hover:underline"
                        onClick={(e) => { e.stopPropagation(); navigate(`/cluster/${inc.cluster_id}`); }}>
                        {inc.namespace}
                      </span>
                      <span className="text-xs px-2 py-0.5 rounded bg-[#212121] text-[#0071C5]">{inc.cluster_id}</span>
                      {inc.failure_class && (
                        <span className="text-xs px-2 py-0.5 rounded bg-[#F0AB00]/20 text-[#F0AB00]">{inc.failure_class}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-[#6A6E73]">
                      <span>{inc.signal_count} signals</span>
                      <span>{inc.remediation_options.length} fixes</span>
                      <span>{inc.evidence.inferences.length} analyses</span>
                      <span>{relativeTime(inc.last_seen)}</span>
                      <span>{isExpanded ? '▼' : '▶'}</span>
                    </div>
                  </div>

                  {/* Root cause summary — always visible */}
                  {rca?.root_cause ? (
                    <p className="text-sm text-[#e0e0e0] mb-2">{String(rca.root_cause)}</p>
                  ) : inc.evidence.inferences.length > 0 ? (
                    <p className="text-sm text-[#a0a0a0] mb-2">{(() => {
                      const parsed = tryParseJSON(inc.evidence.inferences[0].output_summary);
                      return String(parsed?.root_cause || parsed?.explanation || inc.evidence.inferences[0].output_summary || '').slice(0, 200);
                    })()}</p>
                  ) : null}

                  {/* Signal type pills — collapsed preview */}
                  {inc.evidence.signals.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {[...new Set(inc.evidence.signals.map(s => s.type))].slice(0, 5).map(t => (
                        <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-[#212121] text-[#6A6E73]">{t.replace(/_/g, ' ')}</span>
                      ))}
                      {inc.evidence.signals.length > 5 && (
                        <span className="text-[10px] text-[#6A6E73]">+{inc.evidence.signals.length - 5} more</span>
                      )}
                    </div>
                  )}
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="border-t border-[#333] p-5 space-y-5 bg-[#0f0f0f]">

                    {/* Incident Timeline */}
                    <div className="grid grid-cols-3 gap-3 text-xs">
                      <div className="bg-[#1a1a1a] rounded p-2">
                        <span className="text-[#6A6E73] uppercase">First Seen</span>
                        <div className="text-white mt-0.5">{inc.first_seen ? new Date(inc.first_seen).toLocaleString() : '—'}</div>
                      </div>
                      <div className="bg-[#1a1a1a] rounded p-2">
                        <span className="text-[#6A6E73] uppercase">Last Seen</span>
                        <div className="text-white mt-0.5">{inc.last_seen ? new Date(inc.last_seen).toLocaleString() : '—'}</div>
                      </div>
                      <div className="bg-[#1a1a1a] rounded p-2">
                        <span className="text-[#6A6E73] uppercase">Status</span>
                        <div className="mt-0.5 font-bold" style={{ color: inc.status === 'open' ? '#EE0000' : '#3E8635' }}>{inc.status.toUpperCase()}</div>
                      </div>
                    </div>

                    {/* Evidence Chain — all signals */}
                    <div>
                      <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
                        Evidence Chain ({inc.evidence.signals.length} signals)
                      </div>
                      <div className="space-y-1 max-h-64 overflow-y-auto">
                        {inc.evidence.signals.map((sig, i) => (
                          <div key={i} className="flex items-center gap-3 text-xs bg-[#1a1a1a] rounded px-3 py-2">
                            <span className="text-[#6A6E73] font-mono w-4 shrink-0">{i + 1}</span>
                            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: SEV_COLORS[sig.severity] || '#6A6E73' }} />
                            <span className="text-white font-medium">{sig.type.replace(/_/g, ' ')}</span>
                            <span className="text-[#6A6E73] truncate">{sig.resource}</span>
                            <span className="text-[#6A6E73] ml-auto shrink-0">{sig.ts ? relativeTime(sig.ts) : ''}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Classification */}
                    {inc.classification && (
                      <div>
                        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">Classification</div>
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-bold text-[#F0AB00]">{inc.classification.failure_class}</span>
                          <span className="text-xs text-[#6A6E73]">confidence: {(inc.classification.confidence * 100).toFixed(0)}%</span>
                          <span className="text-xs text-[#6A6E73]">model: {inc.classification.model}</span>
                        </div>
                      </div>
                    )}

                    {/* RCA */}
                    {rca && (
                      <div>
                        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">Root Cause Analysis</div>
                        <div className="bg-[#1a1a1a] rounded-lg p-4 space-y-3">
                          <div>
                            <span className="text-[10px] text-[#6A6E73] uppercase">Root Cause</span>
                            <p className="text-sm text-white mt-0.5">{String(rca.root_cause)}</p>
                          </div>
                          {rca.category ? (
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] text-[#6A6E73] uppercase">Category</span>
                              <span className="text-xs px-2 py-0.5 rounded bg-[#F0AB00]/20 text-[#F0AB00]">{String(rca.category)}</span>
                              {rca.confidence != null && (
                                <span className="text-xs text-[#6A6E73]">{(Number(rca.confidence) * 100).toFixed(0)}% confidence</span>
                              )}
                            </div>
                          ) : null}
                          {Array.isArray(rca.evidence_chain) && rca.evidence_chain.length > 0 && (
                            <div>
                              <span className="text-[10px] text-[#6A6E73] uppercase">Evidence Chain</span>
                              <div className="mt-1 space-y-1">
                                {(rca.evidence_chain as string[]).map((step, i) => (
                                  <div key={i} className="flex items-start gap-2 text-xs text-[#a0a0a0]">
                                    <span className="text-[#6A6E73] shrink-0">{i + 1}.</span>
                                    <span>{step}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Remediation Options */}
                    {inc.remediation_options.length > 0 && (
                      <div>
                        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">
                          Remediation Options ({inc.remediation_options.length})
                        </div>
                        <div className="space-y-2">
                          {inc.remediation_options.map((rem, i) => (
                            <div key={i} className="bg-[#1a1a1a] rounded-lg p-3 flex items-center gap-3">
                              <span className="text-xs font-bold px-1.5 py-0.5 rounded"
                                style={{ backgroundColor: `${RISK_COLORS[rem.risk] || '#6A6E73'}20`, color: RISK_COLORS[rem.risk] || '#6A6E73' }}>
                                {rem.risk}
                              </span>
                              <div className="flex-1">
                                <div className="text-sm text-white">{rem.action}</div>
                                {rem.command && (
                                  <code className="text-xs text-[#6A6E73] font-mono mt-0.5 block">{rem.command}</code>
                                )}
                              </div>
                              <span className="text-[10px] text-[#6A6E73]">{rem.source}</span>
                              {canExecute && rem.command && (
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleExecuteClick(rem.command!, inc.namespace, inc.cluster_id); }}
                                  className="px-2 py-1 rounded text-xs font-bold bg-[#3E8635] text-white hover:bg-[#2d6427]"
                                >
                                  Execute
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Inference History */}
                    {inc.evidence.inferences.length > 0 && (
                      <div>
                        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">AI Analysis History</div>
                        <div className="space-y-2">
                          {inc.evidence.inferences.map((inf, i) => {
                            const parsed = inf.output_summary ? tryParseJSON(inf.output_summary) : null;
                            const displayText = parsed
                              ? String(parsed.root_cause || parsed.explanation || parsed.fix || inf.output_summary)
                              : inf.output_summary;
                            return (
                              <div key={i} className="bg-[#1a1a1a] rounded px-3 py-2 text-xs">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="text-white font-medium">{inf.type.replace(/_/g, ' ')}</span>
                                  <span className="text-[#6A6E73]">{inf.model}</span>
                                  <span className="text-[#6A6E73] ml-auto">{inf.ts ? relativeTime(inf.ts) : ''}</span>
                                </div>
                                <p className="text-[#a0a0a0] whitespace-pre-wrap">{displayText}</p>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-2 pt-2 border-t border-[#333]">
                      <button onClick={() => fetch(`/api/v1/incidents/${inc.id}/resolve`, { method: 'POST' })}
                        className="px-3 py-1.5 rounded text-xs font-bold bg-[#3E8635] text-white">
                        Resolve
                      </button>
                      <button onClick={() => fetch(`/api/v1/incidents/${inc.id}/suppress`, { method: 'POST' })}
                        className="px-3 py-1.5 rounded text-xs font-bold bg-[#333] text-[#6A6E73] hover:text-white">
                        Suppress
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {/* Remediation Confirmation Modal */}
      {modal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => setModal(null)}>
          <div className="bg-[#1a1a1a] border border-[#333] rounded-xl p-6 max-w-lg w-full mx-4 space-y-4" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-white">Remediation</h3>

            <div>
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider mb-1">Command</div>
              <code className="text-sm text-yellow-400 font-mono bg-[#111] p-2 rounded block">{modal.command}</code>
            </div>

            {modal.parsed && (
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div><span className="text-[#6A6E73]">Namespace:</span> <span className="text-white">{(modal.parsed as Record<string,string>).namespace}</span></div>
                <div><span className="text-[#6A6E73]">Command:</span> <span className="text-white">{(modal.parsed as Record<string,string>).command}</span></div>
                <div><span className="text-[#6A6E73]">Resource:</span> <span className="text-white">{(modal.parsed as Record<string,string>).resource_kind}/{(modal.parsed as Record<string,string>).resource_name}</span></div>
                <div>
                  <span className="text-[#6A6E73]">Type:</span>{' '}
                  <span className={`font-bold ${(modal.parsed as Record<string,unknown>).read_only ? 'text-[#3E8635]' : 'text-[#F0AB00]'}`}>
                    {(modal.parsed as Record<string,unknown>).read_only ? 'Read-only' : 'Write'}
                  </span>
                </div>
              </div>
            )}

            {modal.status === 'blocked' && (
              <div className="bg-[#C9190B20] border border-[#C9190B] rounded p-3 text-sm text-[#C9190B]">
                Blocked: {modal.result}
              </div>
            )}

            {modal.status === 'done' && (
              <div className="bg-[#3E863520] border border-[#3E8635] rounded p-3">
                <div className="text-xs text-[#3E8635] font-bold mb-1">Result</div>
                <pre className="text-xs text-white font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">{modal.result}</pre>
              </div>
            )}

            {modal.status === 'error' && (
              <div className="bg-[#C9190B20] border border-[#C9190B] rounded p-3 text-sm text-[#C9190B]">
                {modal.result}
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button onClick={() => setModal(null)} className="px-4 py-2 rounded text-sm text-[#6A6E73] hover:text-white">
                {modal.status === 'done' ? 'Close' : 'Cancel'}
              </button>
              {modal.status === 'ready' && (
                <button onClick={confirmExecute} className="px-4 py-2 rounded text-sm font-bold bg-[#3E8635] text-white hover:bg-[#2d6427]">
                  Confirm Execute
                </button>
              )}
              {modal.status === 'executing' && (
                <span className="px-4 py-2 text-sm text-[#F0AB00]">Executing...</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
