import type { MetricsSnapshot } from '../api/client';

interface Props {
  timeline: MetricsSnapshot[];
}

export default function MetricsTimeline({ timeline }: Props) {
  if (!timeline.length) return null;

  const models = new Set<string>();
  timeline.forEach(s => Object.keys(s.models).forEach(m => models.add(m)));
  const modelList = Array.from(models);

  return (
    <section className="bg-gray-900 rounded-xl p-6 border border-gray-800">
      <h2 className="text-lg font-semibold mb-4">Run Metrics Timeline ({timeline.length} snapshots)</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 uppercase border-b border-gray-800">
              <th className="text-left py-1 px-2">Time</th>
              <th className="text-right py-1 px-2">Done</th>
              <th className="text-right py-1 px-2">Conc</th>
              {modelList.map(m => (
                <th key={m} className="text-right py-1 px-2" colSpan={3}>
                  <span className="font-mono">{m.split('-')[0]}</span>
                  <div className="flex justify-end gap-2 text-[10px] text-gray-600 font-normal normal-case">
                    <span>run</span><span>queue</span><span>kv%</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {timeline.map((s, i) => (
              <tr key={i} className="border-b border-gray-800/30 hover:bg-gray-800/20">
                <td className="py-1 px-2 tabular-nums text-gray-400">{(s.t_ms / 1000).toFixed(1)}s</td>
                <td className="py-1 px-2 text-right tabular-nums">{s.completed}</td>
                <td className="py-1 px-2 text-right tabular-nums">{s.concurrency}</td>
                {modelList.map(m => {
                  const md = s.models[m] || {};
                  const running = md.requests_running ?? 0;
                  const waiting = md.requests_waiting ?? 0;
                  const kv = md.kv_cache_pct ?? 0;
                  return (
                    <td key={m} className="py-1 px-2 text-right tabular-nums" colSpan={3}>
                      <span className={running > 0 ? 'text-green-400 font-bold' : 'text-gray-600'}>{running}</span>
                      <span className="text-gray-700 mx-1">/</span>
                      <span className={waiting > 0 ? 'text-yellow-400' : 'text-gray-600'}>{waiting}</span>
                      <span className="text-gray-700 mx-1">/</span>
                      <span className={kv > 10 ? 'text-orange-400' : 'text-gray-600'}>{kv}%</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
