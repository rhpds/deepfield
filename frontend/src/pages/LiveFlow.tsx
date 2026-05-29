import { useState, useEffect, useRef, useCallback } from 'react';

interface AgentEvent {
  ts: string;
  tier: string;
  action: string;
  filter?: string;
  signal_id?: string;
  reason?: string;
  model?: string;
  latency_ms?: number;
  tokens_out?: number;
  evidence?: Record<string, unknown>;
  [key: string]: unknown;
}

interface LiveState {
  metrics?: Record<string, number>;
  totals?: Record<string, number>;
  agent_log?: AgentEvent[];
  model_stats?: Record<string, { calls: number; avg_latency: number; avg_tps: number }>;
}

const STAGE_CONFIG = [
  { id: 'raw', label: 'Raw Signals', color: '#6A6E73', icon: '⚡' },
  { id: 'nano', label: 'Nano-Agents', color: '#0071C5', icon: '🔬' },
  { id: 'correlation', label: 'Correlation', color: '#F0AB00', icon: '🔗' },
  { id: 'llm', label: 'LLM Inference', color: '#EE0000', icon: '🧠' },
  { id: 'insight', label: 'Insights', color: '#3E8635', icon: '✓' },
];

function relativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 0) return 'now';
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ago`;
}

const ACTION_COLORS: Record<string, string> = {
  escalate: '#EE0000',
  keep: '#3E8635',
  drop: '#4d4d4d',
  suppress: '#F0AB00',
  dedupe: '#6A6E73',
  finding: '#F0AB00',
  inference_complete: '#3E8635',
  inference_error: '#C9190B',
  enrich: '#0071C5',
};

export default function LiveFlow() {
  const [live, setLive] = useState<LiveState | null>(null);
  const latestSSE = useRef<LiveState | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const flushSSE = useCallback(() => {
    if (latestSSE.current) setLive(latestSSE.current);
  }, []);

  useEffect(() => {
    const es = new EventSource('/api/v1/stream');
    const handle = (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data);
        if (d.metrics) latestSSE.current = d;
      } catch { /* ignore */ }
    };
    es.addEventListener('live', handle);
    es.addEventListener('session', handle);
    const timer = setInterval(flushSSE, 1500);
    return () => { es.close(); clearInterval(timer); };
  }, [flushSSE]);

  const m = live?.metrics ?? {};
  const events = (live?.agent_log ?? []).slice(-30).reverse();

  const stageValues = [
    m.raw_signals ?? 0,
    (m.raw_signals ?? 0) - (m.dropped ?? 0),
    m.findings ?? 0,
    m.reasoning_tasks ?? 0,
    m.inference_completed ?? 0,
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>
          Live Event Flow
        </h1>
        <p className="text-sm text-[#6A6E73]">Real-time signal processing pipeline</p>
      </div>

      {/* Pipeline Flow Diagram */}
      <div className="border border-[#333] rounded-xl p-6">
        <div className="flex items-center justify-between gap-2">
          {STAGE_CONFIG.map((stage, i) => (
            <div key={stage.id} className="flex items-center gap-2 flex-1">
              <div className="flex-1 text-center">
                <div
                  className="rounded-xl p-4 border-2 transition-all"
                  style={{
                    borderColor: stage.color,
                    backgroundColor: `${stage.color}15`,
                  }}
                >
                  <div className="text-2xl mb-1">{stage.icon}</div>
                  <div
                    className="text-2xl font-bold text-white tabular-nums"
                    style={{ fontFamily: 'Red Hat Display' }}
                  >
                    {stageValues[i]?.toLocaleString() ?? '0'}
                  </div>
                  <div className="text-[10px] text-[#6A6E73] uppercase tracking-wider mt-1">
                    {stage.label}
                  </div>
                </div>
              </div>
              {i < STAGE_CONFIG.length - 1 && (
                <div className="text-[#6A6E73] text-lg shrink-0">→</div>
              )}
            </div>
          ))}
        </div>

        {/* Compression summary */}
        <div className="flex items-center justify-center gap-6 mt-4 text-sm">
          <span className="text-[#6A6E73]">
            Compression: <span className="text-white font-bold">{m.compression_ratio ?? 0}:1</span>
          </span>
          <span className="text-[#6A6E73]">
            Escalation: <span className="text-white font-bold">{m.llm_escalation_pct ?? 0}%</span>
          </span>
          <span className="text-[#6A6E73]">
            Sig/s: <span className="text-white font-bold tabular-nums">{(m.signals_per_second ?? 0).toFixed(0)}</span>
          </span>
        </div>
      </div>

      {/* Live Event Stream */}
      <div className="border border-[#333] rounded-xl p-4">
        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
          Live Agent Events
        </div>

        {events.length === 0 ? (
          <div className="text-sm text-[#6A6E73] text-center py-8">
            Waiting for events...
          </div>
        ) : (
          <div ref={scrollRef} className="space-y-1 max-h-[500px] overflow-y-auto">
            {events.map((ev, i) => {
              const color = ACTION_COLORS[ev.action] ?? '#6A6E73';
              const tierLabel = ev.tier === 'nano' ? 'AGENT' : ev.tier === 'correlation' ? 'CORR' : ev.tier === 'macro' ? 'LLM' : ev.tier?.toUpperCase() ?? '?';

              return (
                <div
                  key={i}
                  className="flex items-center gap-3 px-3 py-2 rounded text-xs bg-[#1a1a1a] hover:bg-[#212121] transition-colors"
                  style={{ borderLeft: `3px solid ${color}` }}
                >
                  {/* Tier badge */}
                  <span
                    className="text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0"
                    style={{ backgroundColor: `${color}25`, color }}
                  >
                    {tierLabel}
                  </span>

                  {/* Action */}
                  <span className="font-medium text-white shrink-0">
                    {ev.action}
                  </span>

                  {/* Details */}
                  <span className="text-[#6A6E73] truncate flex-1">
                    {ev.filter && `${ev.filter}`}
                    {ev.model && `${ev.model}`}
                    {ev.reason && ` — ${ev.reason}`}
                    {ev.signal_id && ` [${ev.signal_id}]`}
                    {ev.latency_ms != null && ` ${ev.latency_ms.toFixed(0)}ms`}
                    {ev.tokens_out != null && ` ${ev.tokens_out} tok`}
                  </span>

                  {/* Timestamp */}
                  <span className="text-[#4d4d4d] shrink-0 tabular-nums">
                    {ev.ts ? relativeTime(ev.ts) : ''}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Model Activity */}
      {live?.model_stats && Object.keys(live.model_stats).length > 0 && (
        <div className="border border-[#333] rounded-xl p-4">
          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">
            Active Models
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(live.model_stats).map(([model, stats]) => (
              <div key={model} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3">
                <div className="text-xs text-[#6A6E73] truncate mb-1 font-mono">{model}</div>
                <div className="text-lg font-bold text-white tabular-nums">{stats.calls}</div>
                <div className="text-[10px] text-[#6A6E73]">
                  {stats.avg_tps.toFixed(0)} tok/s · {stats.avg_latency.toFixed(0)}ms
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
