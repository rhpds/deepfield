import { useState, useEffect } from 'react';

interface AgentStats {
  total_evaluated: number;
  escalated: number;
  kept: number;
  suppressed: number;
  deduped: number;
  dropped: number;
  errors: number;
}

export default function AgentObservatory() {
  const [agents, setAgents] = useState<Record<string, AgentStats>>({});
  const [decisions, setDecisions] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const resp = await fetch('/api/v1/observatory/agents');
        const data = await resp.json();
        if (data.agents) setAgents(data.agents);
        if (data.recent_decisions) setDecisions(data.recent_decisions);
      } catch { /* */ }
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  const totalEvaluated = Object.values(agents).reduce((s, a) => s + a.total_evaluated, 0);
  const totalEscalated = Object.values(agents).reduce((s, a) => s + a.escalated, 0);
  const totalSuppressed = Object.values(agents).reduce((s, a) => s + a.suppressed, 0);

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white" style={{ fontFamily: 'Red Hat Display' }}>Agent Observatory</h1>
        <span className="text-xs text-[#6A6E73]">Nano → Micro → Macro pipeline observability</span>
      </div>

      {/* Aggregate stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-white tabular-nums">{totalEvaluated.toLocaleString()}</div>
          <div className="text-[10px] text-[#6A6E73]">Total Evaluated</div>
        </div>
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-orange-400 tabular-nums">{totalEscalated}</div>
          <div className="text-[10px] text-[#6A6E73]">Escalated</div>
        </div>
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-[#6A6E73] tabular-nums">{totalSuppressed}</div>
          <div className="text-[10px] text-[#6A6E73]">Suppressed</div>
        </div>
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-yellow-400 tabular-nums">{Object.keys(agents).length}</div>
          <div className="text-[10px] text-[#6A6E73]">Active Agents</div>
        </div>
        <div className="rounded-lg p-3 border border-[#333] text-center">
          <div className="text-2xl font-bold text-[#3E8635] tabular-nums">
            {totalEvaluated > 0 ? ((1 - totalEscalated / totalEvaluated) * 100).toFixed(1) : '0'}%
          </div>
          <div className="text-[10px] text-[#6A6E73]">Filter Rate</div>
        </div>
      </div>

      {/* Per-agent cards */}
      <div className="rounded-xl p-4 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Nano Agents</span>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
          {Object.entries(agents).map(([name, stats]) => {
            const total = stats.total_evaluated;
            const escPct = total > 0 ? ((stats.escalated / total) * 100).toFixed(1) : '0';
            return (
              <div key={name} className="bg-[#1a1a1a] rounded p-3 border-l-2 border-[#6A6E73]">
                <div className="text-xs font-mono text-[#6A6E73] truncate">{name}</div>
                <div className="text-lg font-bold text-white mt-1">{total.toLocaleString()}</div>
                <div className="text-[10px] text-[#6A6E73]">evaluated</div>
                <div className="flex gap-2 mt-1 text-[10px] tabular-nums">
                  <span className="text-orange-400">{stats.escalated} esc</span>
                  <span className="text-[#6A6E73]">{stats.suppressed} sup</span>
                  <span className="text-[#6A6E73]">{stats.deduped} dup</span>
                  <span className="text-[#6A6E73]">{stats.kept} kept</span>
                </div>
                {total > 0 && (
                  <div className="mt-1 h-1.5 bg-[#252525] rounded-full overflow-hidden flex">
                    <div className="h-full bg-orange-400" style={{ width: `${escPct}%` }} />
                    <div className="h-full bg-[#6A6E73]" style={{ width: `${100 - Number(escPct)}%` }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Recent decisions */}
      <div className="rounded-xl p-4 border border-[#333]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wide font-semibold">Recent Decisions ({decisions.length})</span>
        <div className="mt-2 space-y-1 max-h-96 overflow-y-auto">
          {decisions.slice().reverse().map((d, i) => {
            const outcome = String(d.outcome ?? '');
            const color = outcome === 'escalate' ? 'border-orange-400' : outcome === 'suppress' ? 'border-[#6A6E73]' : outcome === 'dedupe' ? 'border-yellow-400' : 'border-[#333]';
            return (
              <div key={i} className={`bg-[#1a1a1a] rounded p-2 text-xs border-l-2 ${color}`}>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[#6A6E73]">{String(d.filter_name ?? '')}</span>
                  <span className={`font-bold ${outcome === 'escalate' ? 'text-orange-400' : 'text-[#6A6E73]'}`}>{outcome}</span>
                  <span className="text-[#6A6E73]">{String(d.reason ?? '')}</span>
                  <span className="text-[#6A6E73] ml-auto text-[10px]">{d._ts ? new Date(String(d._ts)).toLocaleTimeString() : ''}</span>
                </div>
                {d.evidence ? (
                  <div className="text-[10px] text-[#6A6E73] mt-0.5 truncate">{JSON.stringify(d.evidence).slice(0, 120)}</div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {!Object.keys(agents).length && (
        <div className="text-center py-12 text-[#6A6E73]">
          <p className="text-lg mb-2">No agent data yet</p>
          <p className="text-sm">Start a Live Monitoring or Simulator session to see agent activity.</p>
        </div>
      )}
    </div>
  );
}
