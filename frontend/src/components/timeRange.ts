export type TimeRangeKey = '5m' | '15m' | '1h' | '6h' | '24h' | '7d';

export interface TimeRange {
  key: TimeRangeKey;
  label: string;
  ms: number;
}

export const TIME_RANGES: TimeRange[] = [
  { key: '5m',  label: '5m',  ms: 5 * 60 * 1000 },
  { key: '15m', label: '15m', ms: 15 * 60 * 1000 },
  { key: '1h',  label: '1h',  ms: 60 * 60 * 1000 },
  { key: '6h',  label: '6h',  ms: 6 * 60 * 60 * 1000 },
  { key: '24h', label: '24h', ms: 24 * 60 * 60 * 1000 },
  { key: '7d',  label: '7d',  ms: 7 * 24 * 60 * 60 * 1000 },
];

export const RANGE_SECONDS: Record<TimeRangeKey, number> = {
  '5m': 300, '15m': 900, '1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800,
};
