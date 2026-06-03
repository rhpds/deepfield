# DeepField Frontend

React 19 + TypeScript + Tailwind CSS 4 + Vite 8 dashboard for DeepField signal intelligence.

## Setup

```bash
npm install
npm run dev     # http://localhost:3100, proxies /api to backend
npm run build   # Production build → dist/
```

The production build is copied to `backend/static/` and served by the FastAPI backend.

## Pages

12 pages in 3 nav groups (Monitor / Pipeline / Quality):

| Page | File | Route | Polls |
|------|------|-------|-------|
| Fleet Overview | `FleetOverview.tsx` | `/` | 10s |
| Incidents | `Incidents.tsx` | `/incidents` | 10s |
| Live Flow | `LiveFlow.tsx` | `/live` | SSE stream |
| Agents | `SignalPipeline.tsx` | `/pipeline` | 5s (workers), 10s (agents) |
| LLM Models | `LLMObservatory.tsx` | `/llm` | 10s |
| Rubrics | `Tuning.tsx` | `/tuning` | 30s |
| Scenarios | `Scenarios.tsx` | `/scenarios` | — |
| Replay | `Replay.tsx` | `/replay` | 5s (list), 3s (detail) |
| Cluster Detail | `ClusterDetail.tsx` | `/cluster/:id` | 10s |
| Simulator | `LivePanel.tsx` | `/simulator` | — |

## Shared Components

| Component | Purpose |
|-----------|---------|
| `HeroMetric` | Large centered metric display |
| `PressureGauge` | Vertical gauge with zones |
| `FunnelChart` | Horizontal bar funnel |
| `MetricsTimeline` | Tabular metrics over time |
| `ModelTable` | Model stats table |
| `TimeRangeContext` | Global time-range state + picker |

## Patterns

**Styling:** Tailwind utility classes with dark theme. Cards: `bg-[#212121] border border-[#2e2e2e] rounded-lg p-4`. Sections: `border border-[#333] rounded-xl p-4`. Headers: `text-xs text-[#6A6E73] uppercase tracking-wider font-bold`.

**Colors:** `#3E8635` (healthy/green), `#F0AB00` (warning/amber), `#C9190B` (failing/red), `#6A6E73` (muted), `#0071C5` (primary/blue).

**Data fetching:** `useEffect` + `setInterval` + cancelled flag. No react-query for polling.

**Charts:** recharts 3.8 (LineChart, BarChart) with dark theme overrides: `stroke="#333"` grid, `fill="#6A6E73"` tick text, tooltip `bg-[#1a1a1a] border border-[#333]`.

## Adding a New Page

1. Create `src/pages/YourPage.tsx`
2. In `App.tsx`: import it, add to a nav group's `items` array, add a `<Route>` element
3. Follow the polling pattern from an existing page (e.g., `Tuning.tsx` for 30s polling)
