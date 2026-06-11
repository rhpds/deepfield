import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, CartesianGrid, Legend, Cell } from 'recharts';

interface RubricResult {
  score: 'healthy' | 'warning' | 'failing';
  checks: Array<[string, string]>;
}

interface EvalResult {
  cluster_id: string;
  timestamp: string;
  overall: 'healthy' | 'warning' | 'failing';
  rubrics: Record<string, RubricResult>;
}

interface Proposal {
  proposal_id: string;
  cluster_id: string;
  category: string;
  evidence: Record<string, unknown>;
  impact_estimate: string;
  confidence: number;
  status: string;
  created_at: string;
}

interface ProfileData {
  cluster_id: string;
  confidence: number;
  dedup_windows: Record<string, number>;
  namespace_noise_scores: Record<string, number>;
  namespace_dampen_thresholds: Record<string, number>;
  baseline_signals_per_second: number;
  model_health: Record<string, { calls: number; errors: number; error_rate: number; avg_latency: number }>;
}

interface FeedbackSummary {
  window: string;
  by_model: Record<string, { up: number; down: number; total: number; approval_rate: number }>;
  by_task_type: Record<string, { up: number; down: number; total: number; approval_rate: number }>;
  by_target_type: Record<string, { up: number; down: number; total: number; approval_rate: number }>;
  negative_comments: Array<{ incident_id: string; target_type: string; model: string; task_type: string; comment: string; created_at: string }>;
}

interface HistoryEntry {
  timestamp: string;
  overall: string;
  rubrics: Record<string, string>;
  source: string;
}

interface HistoryData {
  evaluations: HistoryEntry[];
  trend: { overall: string; rubrics: Record<string, string> };
}

const SCORE_COLORS: Record<string, string> = { healthy: '#3E8635', warning: '#F0AB00', failing: '#C9190B' };
const TREND_ICONS: Record<string, { symbol: string; color: string }> = {
  improving: { symbol: '▲', color: '#3E8635' },
  degrading: { symbol: '▼', color: '#C9190B' },
  stable: { symbol: '—', color: '#6A6E73' },
  insufficient_data: { symbol: '·', color: '#6A6E73' },
};
const RUBRIC_LABELS: Record<string, string> = {
  compression_quality: 'Compression',
  classification_accuracy: 'Classification',
  inference_value: 'Inference',
  signal_coverage: 'Coverage',
  tuning_safety: 'Safety',
};
const SCORE_VALUE: Record<string, number> = { healthy: 2, warning: 1, failing: 0 };
const RUBRIC_COLORS: Record<string, string> = {
  compression_quality: '#0071C5',
  classification_accuracy: '#F0AB00',
  inference_value: '#C9190B',
  signal_coverage: '#3E8635',
  tuning_safety: '#6A6E73',
};

export default function Tuning() {
  const [evaluation, setEvaluation] = useState<EvalResult | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [history, setHistory] = useState<HistoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [clusters, setClusters] = useState<string[]>([]);
  const [selectedCluster, setSelectedCluster] = useState('infra01');
  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackSummary | null>(null);

  useEffect(() => {
    fetch('/api/v1/tuning/clusters').then(r => r.ok ? r.json() : null).then(d => {
      if (d?.clusters?.length) {
        setClusters(d.clusters);
        setSelectedCluster(d.clusters[0]);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const c = selectedCluster;
        const [evalRes, propRes, profRes, histRes, fbRes] = await Promise.all([
          fetch(`/api/v1/tuning/evaluate/${c}`),
          fetch('/api/v1/tuning/proposals'),
          fetch(`/api/v1/tuning/profile/${c}`),
          fetch(`/api/v1/tuning/evaluate/${c}/history`),
          fetch('/api/v1/feedback/summary?window=7d'),
        ]);
        if (cancelled) return;
        if (evalRes.ok) setEvaluation(await evalRes.json());
        if (propRes.ok) { const d = await propRes.json(); setProposals(d.proposals || []); }
        if (profRes.ok) setProfile(await profRes.json());
        if (histRes.ok) setHistory(await histRes.json());
        if (fbRes.ok) setFeedbackSummary(await fbRes.json());
      } catch { /* */ }
      if (!cancelled) setLoading(false);
    }
    setLoading(true);
    load();
    const poll = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(poll); };
  }, [selectedCluster]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 animate-pulse space-y-6">
        <div className="h-10 bg-[#212121] rounded w-48" />
        <div className="grid grid-cols-5 gap-4">{[1,2,3,4,5].map(i => <div key={i} className="bg-[#212121] rounded-lg h-28" />)}</div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>Pipeline Quality</h1>
          <p className="text-sm text-[#6A6E73]">EDD rubrics — continuous evaluation of signal intelligence quality</p>
        </div>
        {clusters.length > 1 && (
          <div className="flex gap-1">
            {clusters.map(c => (
              <button key={c} onClick={() => setSelectedCluster(c)}
                className={`px-3 py-1.5 rounded text-xs font-bold transition ${
                  c === selectedCluster ? 'bg-white/15 text-white' : 'text-[#6A6E73] hover:text-white hover:bg-white/10'
                }`}>
                {c}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Overall score */}
      {evaluation && (
        <div className="flex items-center gap-4">
          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">Overall</div>
          <span className="text-lg font-bold px-4 py-1 rounded-full"
            style={{ backgroundColor: `${SCORE_COLORS[evaluation.overall]}20`, color: SCORE_COLORS[evaluation.overall] }}>
            {evaluation.overall.toUpperCase()}
          </span>
        </div>
      )}

      {/* Rubric cards */}
      {evaluation && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {Object.entries(evaluation.rubrics).map(([key, rubric]) => {
            const trend = history?.trend?.rubrics?.[key];
            const ti = trend ? TREND_ICONS[trend] || TREND_ICONS.stable : null;
            return (
              <div key={key} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4"
                style={{ borderTop: `3px solid ${SCORE_COLORS[rubric.score]}` }}>
                <div className="text-xs text-[#6A6E73] uppercase tracking-wider mb-2">{RUBRIC_LABELS[key] || key}</div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-lg font-bold" style={{ color: SCORE_COLORS[rubric.score], fontFamily: 'Red Hat Display' }}>
                    {rubric.score.toUpperCase()}
                  </span>
                  {ti && <span className="text-xs font-bold" style={{ color: ti.color }}>{ti.symbol}</span>}
                </div>
                <div className="space-y-1">
                  {rubric.checks.map(([name, level]) => (
                    <div key={name} className="flex items-center gap-2 text-[10px]">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SCORE_COLORS[level as keyof typeof SCORE_COLORS] || '#6A6E73' }} />
                      <span className="text-[#6A6E73]">{name.replace(/_/g, ' ')}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Rubric History */}
      {history && history.evaluations.length > 0 && (
        <div className="border border-[#333] rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
              Evaluation History ({history.evaluations.length})
            </div>
            {history.trend?.overall && (
              <span className="text-xs font-bold" style={{ color: (TREND_ICONS[history.trend.overall] || TREND_ICONS.stable).color }}>
                {(TREND_ICONS[history.trend.overall] || TREND_ICONS.stable).symbol} {history.trend.overall}
              </span>
            )}
          </div>
          {history.evaluations.length >= 3 && (
            <div className="mb-3">
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={history.evaluations.slice(-20).map(e => ({
                  time: new Date(e.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                  overall: SCORE_VALUE[e.overall] ?? 1,
                  ...Object.fromEntries(Object.entries(e.rubrics || {}).map(([k, v]) => [k, SCORE_VALUE[v as string] ?? 1])),
                }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#6A6E73' }} stroke="#333" />
                  <YAxis domain={[0, 2]} ticks={[0, 1, 2]} tickFormatter={(v: number) => ['FAIL', 'WARN', 'OK'][v] || ''} tick={{ fontSize: 10, fill: '#6A6E73' }} stroke="#333" width={40} />
                  <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333', borderRadius: 6, fontSize: 11 }}
                    formatter={(v, name) => [['failing','warning','healthy'][v as number] || v, RUBRIC_LABELS[name as string] || name]} />
                  <Line dataKey="overall" stroke="#fff" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                  {Object.entries(RUBRIC_COLORS).map(([key, color]) => (
                    <Line key={key} dataKey={key} stroke={color} strokeWidth={1.5} dot={false} type="stepAfter" />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="flex items-center gap-1">
            {history.evaluations.slice(-20).map((e, i) => (
              <div key={i} className="flex flex-col items-center gap-0.5" title={`${new Date(e.timestamp).toLocaleTimeString()} — ${e.overall} (${e.source})`}>
                <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: SCORE_COLORS[e.overall] || '#6A6E73' }} />
                {i % 5 === 0 && <span className="text-[8px] text-[#6A6E73]">{new Date(e.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cluster Profile */}
      {profile && (
        <div className="border border-[#333] rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
              Adaptive Profile — {profile.cluster_id}
            </div>
            <span className="text-xs text-[#6A6E73] flex gap-4">
              <span>Confidence: <span className="text-white font-bold">{(profile.confidence * 100).toFixed(0)}%</span></span>
              <span>Baseline: <span className="text-white font-bold">{profile.baseline_signals_per_second.toFixed(1)} sig/s</span></span>
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {/* Dedup windows */}
            <div>
              <div className="text-[10px] text-[#6A6E73] uppercase mb-2">Learned Dedup Windows</div>
              {Object.keys(profile.dedup_windows).length === 0 ? (
                <p className="text-xs text-[#6A6E73]">Learning... (default 60s)</p>
              ) : (
                <div className="space-y-1">
                  {Object.entries(profile.dedup_windows).map(([type, secs]) => (
                    <div key={type} className="flex justify-between text-xs">
                      <span className="text-[#6A6E73] truncate">{type}</span>
                      <span className="text-white font-mono">{secs}s</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Noise scores */}
            <div>
              <div className="text-[10px] text-[#6A6E73] uppercase mb-2">Namespace Noise Scores</div>
              {Object.keys(profile.namespace_noise_scores).length === 0 ? (
                <p className="text-xs text-[#6A6E73]">Learning...</p>
              ) : (
                <div className="space-y-1">
                  {Object.entries(profile.namespace_noise_scores)
                    .filter(([, v]) => v > 0.05)
                    .sort(([, a], [, b]) => b - a)
                    .slice(0, 8)
                    .map(([ns, score]) => (
                      <div key={ns} className="flex justify-between text-xs">
                        <span className="text-[#6A6E73] truncate">{ns}</span>
                        <span className="font-mono" style={{ color: score > 0.9 ? '#C9190B' : score > 0.5 ? '#F0AB00' : '#3E8635' }}>
                          {(score * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                </div>
              )}
            </div>

            {/* Dampen thresholds */}
            <div>
              <div className="text-[10px] text-[#6A6E73] uppercase mb-2">Dampen Thresholds</div>
              {Object.keys(profile.namespace_dampen_thresholds).length === 0 ? (
                <p className="text-xs text-[#6A6E73]">Default (10) for all</p>
              ) : (
                <div className="space-y-1">
                  {Object.entries(profile.namespace_dampen_thresholds)
                    .sort(([, a], [, b]) => a - b)
                    .slice(0, 8)
                    .map(([ns, threshold]) => (
                      <div key={ns} className="flex justify-between text-xs">
                        <span className="text-[#6A6E73] truncate">{ns}</span>
                        <span className="font-mono" style={{ color: threshold <= 3 ? '#C9190B' : threshold <= 5 ? '#F0AB00' : '#3E8635' }}>
                          {threshold}
                        </span>
                      </div>
                    ))}
                </div>
              )}
            </div>

            {/* Model health */}
            <div>
              <div className="text-[10px] text-[#6A6E73] uppercase mb-2">Model Health</div>
              {Object.keys(profile.model_health).length === 0 ? (
                <p className="text-xs text-[#6A6E73]">No model data yet</p>
              ) : (
                <div className="space-y-1">
                  {Object.entries(profile.model_health).map(([model, h]) => (
                    <div key={model} className="flex justify-between text-xs">
                      <span className="text-[#6A6E73] truncate">{model.replace(/_/g, ' ')}</span>
                      <span className="font-mono" style={{ color: (h.error_rate || 0) > 0.15 ? '#C9190B' : '#3E8635' }}>
                        {((h.error_rate || 0) * 100).toFixed(0)}% err
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Namespace threshold analysis */}
      {profile && (() => {
        const nsMerged = Array.from(new Set([
          ...Object.keys(profile.namespace_noise_scores),
          ...Object.keys(profile.namespace_dampen_thresholds),
        ])).map(ns => ({
          namespace: ns.length > 20 ? ns.slice(0, 18) + '...' : ns,
          noise: Math.round((profile.namespace_noise_scores[ns] || 0) * 100),
          threshold: profile.namespace_dampen_thresholds[ns] || 10,
        })).sort((a, b) => b.noise - a.noise).slice(0, 12);

        if (nsMerged.length === 0) return null;
        return (
          <div className="border border-[#333] rounded-xl p-4">
            <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">Namespace Threshold Analysis</div>
            <ResponsiveContainer width="100%" height={Math.max(180, nsMerged.length * 28)}>
              <BarChart data={nsMerged} layout="vertical" margin={{ left: 10, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#6A6E73' }} stroke="#333" />
                <YAxis dataKey="namespace" type="category" width={130} tick={{ fontSize: 10, fill: '#6A6E73' }} stroke="#333" />
                <Tooltip contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333', borderRadius: 6, fontSize: 11 }}
                  formatter={(v, name) => [name === 'noise' ? `${v}%` : v, name === 'noise' ? 'Noise Score' : 'Dampen Threshold']} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#6A6E73' }} />
                <Bar dataKey="noise" name="Noise %" barSize={10}>
                  {nsMerged.map((d, i) => (
                    <Cell key={i} fill={d.noise > 90 ? '#C9190B' : d.noise > 50 ? '#F0AB00' : '#3E8635'} />
                  ))}
                </Bar>
                <Bar dataKey="threshold" name="Threshold" fill="#0071C5" barSize={10} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        );
      })()}

      {/* Tuning Proposals */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Tuning Proposals ({proposals.length} pending)
        </div>
        {proposals.length === 0 ? (
          <p className="text-sm text-[#6A6E73]">No pending proposals — system is stable or still learning</p>
        ) : (
          <div className="space-y-3">
            {proposals.map(p => (
              <div key={p.proposal_id} className="bg-[#1a1a1a] rounded-lg p-4 border-l-3"
                style={{ borderLeft: `3px solid ${p.category === 'noise_resolution' ? '#F0AB00' : p.category === 'model_rotation' ? '#C9190B' : '#0071C5'}` }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-[#212121] text-[#6A6E73]">{p.category}</span>
                    <span className="text-xs text-[#6A6E73]">confidence: {(p.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <div className="flex gap-2">
                    <button className="px-3 py-1 rounded text-xs font-bold bg-[#3E8635] text-white hover:bg-[#2d6427]"
                      onClick={() => fetch(`/api/v1/tuning/proposals/${p.proposal_id}/approve`, { method: 'POST' })}>
                      Approve
                    </button>
                    <button className="px-3 py-1 rounded text-xs font-bold bg-[#333] text-[#6A6E73] hover:text-white"
                      onClick={() => fetch(`/api/v1/tuning/proposals/${p.proposal_id}/reject`, { method: 'POST' })}>
                      Reject
                    </button>
                  </div>
                </div>
                <p className="text-sm text-[#e0e0e0]">{p.impact_estimate}</p>
                <div className="text-xs text-[#6A6E73] mt-1 font-mono">
                  {JSON.stringify(p.evidence).slice(0, 150)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Human Feedback */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Human Feedback — LLM Output Quality
        </div>
        {!feedbackSummary || Object.keys(feedbackSummary.by_model).length === 0 ? (
          <p className="text-sm text-[#6A6E73]">No feedback submitted yet — rate LLM outputs on the Incidents page to populate this section</p>
        ) : (
          <div className="space-y-4">
            {/* By Model */}
            <div>
              <div className="text-[10px] text-[#6A6E73] uppercase mb-2">Approval Rate by Model</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Object.entries(feedbackSummary.by_model).map(([model, stats]) => (
                  <div key={model} className="bg-[#1a1a1a] rounded-lg p-3">
                    <div className="text-xs text-[#6A6E73] truncate mb-1">{model.replace(/_/g, ' ')}</div>
                    <div className="text-xl font-bold tabular-nums" style={{
                      color: stats.approval_rate >= 0.8 ? '#3E8635' : stats.approval_rate >= 0.5 ? '#F0AB00' : '#C9190B',
                      fontFamily: 'Red Hat Display',
                    }}>
                      {(stats.approval_rate * 100).toFixed(0)}%
                    </div>
                    <div className="flex gap-2 mt-1 text-[10px] text-[#6A6E73]">
                      <span>{stats.up} up</span>
                      <span>{stats.down} down</span>
                      <span>{stats.total} total</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* By Task Type */}
            {Object.keys(feedbackSummary.by_task_type).length > 0 && (
              <div>
                <div className="text-[10px] text-[#6A6E73] uppercase mb-2">Approval Rate by Task Type</div>
                <div className="space-y-1">
                  {Object.entries(feedbackSummary.by_task_type).map(([taskType, stats]) => (
                    <div key={taskType} className="flex items-center gap-3 text-xs">
                      <span className="text-[#6A6E73] w-40 truncate">{taskType.replace(/_/g, ' ')}</span>
                      <div className="flex-1 h-3 bg-[#1a1a1a] rounded overflow-hidden flex">
                        <div className="h-full bg-[#3E8635]" style={{ width: `${stats.approval_rate * 100}%` }} />
                        <div className="h-full bg-[#C9190B]" style={{ width: `${(1 - stats.approval_rate) * 100}%` }} />
                      </div>
                      <span className="text-white font-bold tabular-nums w-12 text-right">{(stats.approval_rate * 100).toFixed(0)}%</span>
                      <span className="text-[#6A6E73] tabular-nums w-16 text-right">{stats.total} ratings</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Negative Comments */}
            {feedbackSummary.negative_comments.length > 0 && (
              <div>
                <div className="text-[10px] text-[#6A6E73] uppercase mb-2">
                  Recent Negative Feedback ({feedbackSummary.negative_comments.length})
                </div>
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {feedbackSummary.negative_comments.map((fb, i) => (
                    <div key={i} className="bg-[#1a1a1a] rounded px-3 py-2 text-xs border-l-2 border-[#C9190B]">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[#C9190B] font-bold">{fb.target_type}</span>
                        <span className="text-[#6A6E73]">{fb.model || '—'}</span>
                        <span className="text-[#6A6E73]">{fb.task_type.replace(/_/g, ' ')}</span>
                        <span className="text-[#6A6E73] ml-auto">{fb.created_at ? new Date(fb.created_at).toLocaleDateString() : ''}</span>
                      </div>
                      <p className="text-[#e0e0e0]">{fb.comment}</p>
                      <span className="text-[10px] text-[#6A6E73] font-mono mt-1 block">incident: {fb.incident_id.slice(0, 8)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
