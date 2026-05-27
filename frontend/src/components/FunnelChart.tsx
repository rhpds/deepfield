import type { SignalFunnel } from '../api/client';

interface Props {
  funnel: SignalFunnel;
}

const STAGES: { key: string; label: string; bg: string }[] = [
  { key: 'raw_signals_received', label: 'Raw Signals', bg: '#6A6E73' },
  { key: 'normalized_signals', label: 'Normalized', bg: '#0071C5' },
  { key: 'retained_signals', label: 'After Filters', bg: '#F0AB00' },
  { key: 'correlated_findings', label: 'Findings', bg: '#EC7A08' },
  { key: 'reasoning_tasks_created', label: 'Reasoning Tasks', bg: '#EE0000' },
  { key: 'final_insights_created', label: 'Insights', bg: '#3E8635' },
];

export default function FunnelChart({ funnel }: Props) {
  const max = funnel.raw_signals_received || 1;

  return (
    <div className="space-y-2">
      {STAGES.map(({ key, label, bg }) => {
        const val = funnel[key as keyof typeof funnel] as number || 0;
        const pct = Math.max((val / max) * 100, 1);
        return (
          <div key={key} className="flex items-center gap-3">
            <div className="w-32 text-right text-xs text-[#6A6E73] shrink-0">{label}</div>
            <div className="flex-1 h-7 bg-[#252525] rounded overflow-hidden relative">
              <div className="h-full rounded transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: bg }} />
              <span className="absolute inset-y-0 left-2 flex items-center text-xs text-white font-mono">
                {val.toLocaleString()}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
