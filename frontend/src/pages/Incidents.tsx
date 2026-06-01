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
    const cleaned = text.replace(/^```json\s*/, '').replace(/```\s*$/, '').trim();
    const start = cleaned.indexOf('{');
    if (start >= 0) return JSON.parse(cleaned.substring(start));
  } catch { /* */ }
  return null;
}

export default function Incidents() {
  const navigate = useNavigate();
  const { range } = useTimeRange();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Total Incidents', value: incidents.length },
          { label: 'Open (High/Crit)', value: openCount, color: openCount > 0 ? '#EE0000' : '#3E8635' },
          { label: 'With RCA', value: withRCA },
          { label: 'With Remediation', value: withRemediation },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <div className="text-2xl font-bold tabular-nums" style={{ color: color || '#fff', fontFamily: 'Red Hat Display' }}>{value}</div>
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
          </div>
        ))}
      </div>

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

                {/* Header — always visible */}
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
                      {inc.failure_class && (
                        <span className="text-xs px-2 py-0.5 rounded bg-[#212121] text-[#F0AB00]">{inc.failure_class}</span>
                      )}
                      <span className="text-xs text-[#6A6E73]">{inc.signal_count} signals</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-[#6A6E73]">{relativeTime(inc.last_seen)}</span>
                      <span className="text-[#6A6E73]">{isExpanded ? '▼' : '▶'}</span>
                    </div>
                  </div>

                  {/* Quick summary */}
                  {rca?.root_cause ? (
                    <p className="text-sm text-[#e0e0e0] line-clamp-2">{String(rca.root_cause)}</p>
                  ) : null}
                  {!rca && inc.evidence.inferences.length > 0 && (
                    <p className="text-sm text-[#a0a0a0] line-clamp-1">{inc.evidence.inferences[0].output_summary}</p>
                  )}
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="border-t border-[#333] p-5 space-y-5 bg-[#0f0f0f]">

                    {/* Evidence Chain */}
                    <div>
                      <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">Evidence Chain</div>
                      <div className="space-y-2">
                        {inc.evidence.signals.slice(-5).map((sig, i) => (
                          <div key={i} className="flex items-center gap-3 text-xs bg-[#1a1a1a] rounded px-3 py-2">
                            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SEV_COLORS[sig.severity] || '#6A6E73' }} />
                            <span className="text-white font-medium">{sig.type}</span>
                            <span className="text-[#6A6E73]">{sig.resource}</span>
                            <span className="text-[#6A6E73] ml-auto">{sig.ts ? relativeTime(sig.ts) : ''}</span>
                          </div>
                        ))}
                        {inc.evidence.signals.length > 5 && (
                          <div className="text-xs text-[#6A6E73] pl-3">+ {inc.evidence.signals.length - 5} more signals</div>
                        )}
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
                                <button className="px-2 py-1 rounded text-xs font-bold bg-[#3E8635] text-white hover:bg-[#2d6427]">
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
    </div>
  );
}
