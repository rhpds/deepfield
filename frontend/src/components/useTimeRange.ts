import { useContext } from 'react';
import { TimeRangeCtx } from './timeRangeState';

export function useTimeRange() {
  return useContext(TimeRangeCtx);
}
