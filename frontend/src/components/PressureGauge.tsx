interface Props {
  value: number;
  max: number;
  label: string;
}

export default function PressureGauge({ value, max, label }: Props) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;

  let color = '#3E8635';
  let zone = 'LOW';
  if (pct > 70) { color = '#EE0000'; zone = 'HIGH'; }
  else if (pct > 40) { color = '#F0AB00'; zone = 'MED'; }

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="text-[10px] text-[#6A6E73] uppercase tracking-wide">{label}</div>
      <div className="relative w-8 h-48 bg-[#252525] rounded-full overflow-hidden border border-[#333]">
        {/* Green / Yellow / Red zones */}
        <div className="absolute bottom-0 left-0 right-0 h-[40%] bg-[#3E8635]/20 rounded-b-full" />
        <div className="absolute bottom-[40%] left-0 right-0 h-[30%] bg-[#F0AB00]/20" />
        <div className="absolute bottom-[70%] left-0 right-0 h-[30%] bg-[#EE0000]/20 rounded-t-full" />
        {/* Fill bar */}
        <div
          className="absolute bottom-0 left-0 right-0 transition-all duration-500 rounded-b-full"
          style={{ height: `${pct}%`, backgroundColor: color }}
        />
        {/* Line marker */}
        <div
          className="absolute left-0 right-0 h-0.5 bg-white transition-all duration-500 shadow-[0_0_6px_rgba(255,255,255,0.8)]"
          style={{ bottom: `${pct}%` }}
        />
      </div>
      <div className="text-xs font-bold tabular-nums" style={{ color }}>{zone}</div>
      <div className="text-sm font-bold text-white tabular-nums">{value}</div>
    </div>
  );
}
