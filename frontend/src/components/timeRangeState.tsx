import { createContext, useContext, useState, useRef, useCallback, type ReactNode } from 'react';
import { type TimeRange, TIME_RANGES } from './timeRange';

const DEFAULT: TimeRange = { key: '1h', label: '1h', ms: 60 * 60 * 1000 };

interface TimeRangeContextValue {
  range: TimeRange;
  setRange: (r: TimeRange) => void;
  since: () => number;
  sinceISO: () => string;
}

export const TimeRangeCtx = createContext<TimeRangeContextValue>({
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
    <TimeRangeCtx.Provider value={{ range, setRange, since, sinceISO }}>
      {children}
    </TimeRangeCtx.Provider>
  );
}

export function TimeRangePicker() {
  const { range, setRange } = useContext(TimeRangeCtx);
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
