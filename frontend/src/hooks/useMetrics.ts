import { useQuery } from '@tanstack/react-query';
import { useTimeRange } from '../components/TimeRangeContext';

export interface MetricsData {
  window: string;
  agents: Record<string, { total_evaluated: number; escalated: number; kept: number; dropped: number; suppressed: number; deduped: number }>;
  signals: { total: number; by_severity: Record<string, number> };
  models: Record<string, { total_calls: number; avg_latency: number; avg_tps: number; total_tokens_in: number; total_tokens_out: number }>;
  funnel: { raw: number; retained: number; findings: number; tasks: number; inferences: number };
  compression_ratio: number;
  signals_per_second: number;
  inference_in_flight: number;
  recent_signals: Array<Record<string, unknown>>;
  recent_decisions: Array<Record<string, unknown>>;
  recent_inferences: Array<Record<string, unknown>>;
}

export function useMetrics() {
  const { range } = useTimeRange();
  return useQuery<MetricsData>({
    queryKey: ['metrics', range.key],
    queryFn: () => fetch(`/api/v1/metrics?window=${range.key}`).then(r => r.json()),
    refetchInterval: 5000,
    staleTime: 2000,
  });
}
