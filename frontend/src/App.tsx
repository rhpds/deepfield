import { useState, useRef, useEffect } from 'react';
import { Routes, Route, NavLink, Outlet, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TimeRangeProvider, TimeRangePicker } from './components/TimeRangeContext';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2000 } },
});
import FleetOverview from './pages/FleetOverview';
import SignalPipeline from './pages/SignalPipeline';
import LiveFlow from './pages/LiveFlow';
import LLMObservatory from './pages/LLMObservatory';
import ClusterDetail from './pages/ClusterDetail';
import LivePanel from './pages/LivePanel';
import Incidents from './pages/Incidents';
import Tuning from './pages/Tuning';
import Scenarios from './pages/Scenarios';
import Replay from './pages/Replay';

interface NavGroup {
  label: string;
  items: { to: string; label: string }[];
}

function NavDropdown({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const isGroupActive = group.items.some(i => location.pathname === i.to);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)}
        className={`px-3 py-2 rounded text-sm font-medium transition flex items-center gap-1 ${isGroupActive ? 'bg-white/15 text-white' : 'text-[#6A6E73] hover:text-white hover:bg-white/10'}`}>
        {group.label}
        <span className="text-[10px]">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-[#212121] border border-[#333] rounded-lg shadow-xl py-1 min-w-[140px] z-50">
          {group.items.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === '/'}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `block px-4 py-2 text-sm transition ${isActive ? 'text-white bg-white/10' : 'text-[#a0a0a0] hover:text-white hover:bg-white/5'}`
              }>
              {label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

function AppLayout() {
  const navGroups: NavGroup[] = [
    { label: 'Monitor', items: [
      { to: '/', label: 'Fleet Overview' },
      { to: '/incidents', label: 'Incidents' },
      { to: '/live', label: 'Live Flow' },
    ]},
    { label: 'Pipeline', items: [
      { to: '/pipeline', label: 'Agents' },
      { to: '/llm', label: 'LLM Models' },
    ]},
    { label: 'Quality', items: [
      { to: '/tuning', label: 'Rubrics' },
      { to: '/scenarios', label: 'Scenarios' },
      { to: '/replay', label: 'Replay' },
    ]},
  ];

  return (
    <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--brand-dark)' }}>
      <header style={{ backgroundColor: 'var(--brand-dark)' }} className="text-white border-b border-[#333]">
        <div className="max-w-7xl mx-auto px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <img src="/logos/redhat.svg" alt="Red Hat" style={{ height: '28px' }} />
              <span className="text-white text-xl font-bold mx-1">X</span>
              <img src="/logos/intel.svg" alt="Intel" style={{ height: '22px' }} />
              <span className="text-[#6A6E73] mx-3">|</span>
              <span className="text-lg font-semibold tracking-tight" style={{ fontFamily: 'Red Hat Display, sans-serif' }}>DeepField</span>
            </div>
            <nav className="flex gap-1">
              {navGroups.map(group => (
                <NavDropdown key={group.label} group={group} />
              ))}
            </nav>
            <TimeRangePicker />
          </div>
        </div>
      </header>
      <div className="h-0.5 flex">
        <div className="flex-1" style={{ backgroundColor: 'var(--brand-primary)' }} />
        <div className="flex-1" style={{ backgroundColor: 'var(--brand-secondary)' }} />
      </div>
      <main className="flex-1">
        <Outlet />
      </main>
      <footer style={{ backgroundColor: 'var(--brand-dark)' }} className="border-t border-[#333] text-[#6A6E73] text-sm py-5">
        <div className="max-w-7xl mx-auto px-6 lg:px-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/logos/redhat.svg" alt="" style={{ height: '16px', opacity: 0.6 }} />
            <span className="text-sm font-bold mx-1">X</span>
            <img src="/logos/intel.svg" alt="" style={{ height: '14px', opacity: 0.6 }} />
          </div>
          <span>Powered by Red Hat OpenShift AI and Intel Gaudi 3</span>
        </div>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
    <TimeRangeProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<FleetOverview />} />
          <Route path="/pipeline" element={<SignalPipeline />} />
          <Route path="/live" element={<LiveFlow />} />
          <Route path="/llm" element={<LLMObservatory />} />
          <Route path="/cluster/:id" element={<ClusterDetail />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/tuning" element={<Tuning />} />
          <Route path="/scenarios" element={<Scenarios />} />
          <Route path="/replay" element={<Replay />} />
          <Route path="/simulator" element={<LivePanel />} />
        </Route>
      </Routes>
    </TimeRangeProvider>
    </QueryClientProvider>
  );
}
