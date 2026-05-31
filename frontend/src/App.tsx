import { Routes, Route, NavLink, Outlet } from 'react-router-dom';
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

function AppLayout() {
  const navItems = [
    { to: '/', label: 'Fleet' },
    { to: '/pipeline', label: 'Pipeline' },
    { to: '/live', label: 'Live Flow' },
    { to: '/llm', label: 'LLM' },
    { to: '/incidents', label: 'Incidents' },
    { to: '/simulator', label: 'Simulator' },
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
              {navItems.map(({ to, label }) => (
                <NavLink key={to} to={to} end={to === '/'}
                  className={({ isActive }) =>
                    `px-3 py-2 rounded text-sm font-medium transition ${isActive ? 'bg-white/15 text-white' : 'text-[#6A6E73] hover:text-white hover:bg-white/10'}`
                  }>
                  {label}
                </NavLink>
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
          <Route path="/simulator" element={<LivePanel />} />
        </Route>
      </Routes>
    </TimeRangeProvider>
    </QueryClientProvider>
  );
}
