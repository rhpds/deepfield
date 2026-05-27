import type { ModelMetrics } from '../api/client';

interface Props {
  metrics: Record<string, ModelMetrics>;
}

const HW_COLORS: Record<string, string> = {
  gaudi3: 'text-orange-400',
  xeon6: 'text-blue-400',
  unknown: 'text-gray-400',
};

export default function ModelTable({ metrics }: Props) {
  const models = Object.values(metrics);
  if (!models.length) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 text-xs uppercase border-b border-gray-800">
            <th className="text-left py-2 px-2">Model</th>
            <th className="text-left py-2 px-2">Hardware</th>
            <th className="text-right py-2 px-2">Requests</th>
            <th className="text-right py-2 px-2">p95 (ms)</th>
            <th className="text-right py-2 px-2">Tok/s</th>
            <th className="text-right py-2 px-2">RPS</th>
            <th className="text-right py-2 px-2">Errors</th>
            <th className="text-center py-2 px-2">Stable</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model_name} className="border-b border-gray-800/50 hover:bg-gray-900/50">
              <td className="py-2 px-2 font-mono text-xs">{m.model_name}</td>
              <td className={`py-2 px-2 font-semibold text-xs ${HW_COLORS[m.hardware_lane] || HW_COLORS.unknown}`}>
                {m.hardware_lane}
              </td>
              <td className="py-2 px-2 text-right tabular-nums">{m.total_requests}</td>
              <td className="py-2 px-2 text-right tabular-nums">{m.p95_latency_ms.toFixed(0)}</td>
              <td className="py-2 px-2 text-right tabular-nums">{m.tokens_per_second.toFixed(1)}</td>
              <td className="py-2 px-2 text-right tabular-nums">{m.requests_per_second.toFixed(1)}</td>
              <td className="py-2 px-2 text-right tabular-nums">{(m.error_rate * 100).toFixed(1)}%</td>
              <td className="py-2 px-2 text-center">
                {m.stable
                  ? <span className="text-green-400 font-bold">YES</span>
                  : <span className="text-red-400 font-bold">NO</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
