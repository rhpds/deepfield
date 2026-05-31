import { createContext, useContext, useState, useRef, useCallback, type ReactNode } from 'react';

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

const DEFAULT: TimeRange = { key: '1h', label: '1h', ms: 60 * 60 * 1000 };

interface TimeRangeContextValue {
  range: TimeRange;
  setRange: (r: TimeRange) => void;
  since: () => number;
  sinceISO: () => string;
}

const Ctx = createContext<TimeRangeContextValue>({
  range: DEFAULT,
  setRange: () => {},
  since: () => Date.now() - DEFAULT.ms,
  sinceISO: () => new Date(Date.now() - DEFAULT.ms).toISOString(),
});

export function TimeRangeProvider({ children }: { children: ReactNode }) {
  const [range, setRangeRaw] = useState<TimeRange>(DEFAULT);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setRange = useCallback((r: TimeRange) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setRangeRaw(r), 150);
  }, []);

  const since = useCallback(() => Date.now() - range.ms, [range.ms]);
  const sinceISO = useCallback(() => new Date(Date.now() - range.ms).toISOString(), [range.ms]);

  return (
    <Ctx.Provider value={{ range, setRange, since, sinceISO }}>
      {children}
    </Ctx.Provider>
  );
}

export function useTimeRange() {
  return useContext(Ctx);
}

export function TimeRangePicker() {
  const { range, setRange } = useTimeRange();
  return (
    <div className="flex gap-0.5 bg-[#1a1a1a] rounded-lg p-0.5">
      {TIME_RANGES.map(r => (
        <button
          key={r.key}
          onClick={() => setRange(r)}
          className={`px-2.5 py-1 rounded text-xs font-medium transition ${
            range.key === r.key
              ? 'bg-white/15 text-white'
              : 'text-[#6A6E73] hover:text-white'
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}
