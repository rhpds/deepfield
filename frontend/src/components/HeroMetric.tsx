interface Props {
  value: number | string;
  label: string;
  sublabel?: string;
  color?: string;
}

export default function HeroMetric({ value, label, sublabel, color = 'text-blue-400' }: Props) {
  return (
    <div className="text-center">
      <div className={`text-5xl font-bold ${color} tabular-nums`}>{typeof value === 'number' ? value.toLocaleString() : value}</div>
      <div className="text-sm text-gray-400 mt-1">{label}</div>
      {sublabel && <div className="text-xs text-gray-600 mt-0.5">{sublabel}</div>}
    </div>
  );
}
