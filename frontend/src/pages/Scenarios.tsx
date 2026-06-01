import { useState, useEffect } from 'react';

interface ScenarioDef {
  id: string;
  name: string;
  namespace: string;
  inject_type: string;
  expected_classification: string;
  execute_remediation: boolean;
  description: string;
}

interface Check {
  check: string;
  passed: boolean;
  detail: string;
}

interface Step {
  step: string;
  status: string;
  reason?: string;
}

interface RunResult {
  scenario_id: string;
  name: string;
  namespace: string;
  status: string;
  steps: Step[];
  checks: Check[];
  error?: string;
  started_at?: string;
  completed_at?: string;
  incident?: Record<string, unknown>;
}

const STATUS_COLORS: Record<string, string> = {
  pass: '#3E8635', fail: '#C9190B', error: '#C9190B', running: '#F0AB00',
};

export default function Scenarios() {
  const [scenarios, setScenarios] = useState<ScenarioDef[]>([]);
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/v1/scenarios').then(r => r.json()).then(d => setScenarios(d.scenarios || []));
    fetch('/api/v1/scenarios/results').then(r => r.json()).then(d => setResults(d.results || {}));
  }, []);

  const runScenario = async (id: string) => {
    setRunning(id);
    setExpanded(id);
    setResults(prev => ({ ...prev, [id]: { scenario_id: id, name: id, namespace: '', status: 'running', steps: [], checks: [] } as RunResult }));
    try {
      await fetch('/api/v1/scenarios/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: id }),
      });
      // Poll for results
      const pollForResult = async () => {
        for (let i = 0; i < 60; i++) {
          await new Promise(r => setTimeout(r, 3000));
          try {
            const resp = await fetch(`/api/v1/scenarios/results/${id}`);
            const raw = await resp.json();
            const result = { ...raw, steps: raw.steps || [], checks: raw.checks || [] } as RunResult;
            setResults(prev => ({ ...prev, [id]: result }));
            if (raw.status && raw.status !== 'running') {
              setRunning(null);
              return;
            }
          } catch { /* keep polling */ }
        }
        setRunning(null);
      };
      pollForResult();
    } catch (e) {
      setResults(prev => ({ ...prev, [id]: { scenario_id: id, name: id, namespace: '', status: 'error', steps: [], checks: [], error: String(e) } as RunResult }));
      setRunning(null);
    }
  };

  const runAll = async () => {
    for (const s of scenarios) {
      await runScenario(s.id);
    }
  };

  const passCount = Object.values(results).filter(r => r.status === 'pass').length;
  const failCount = Object.values(results).filter(r => r.status === 'fail' || r.status === 'error').length;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>Scenario Runner</h1>
          <p className="text-sm text-[#6A6E73]">End-to-end pipeline testing — inject, detect, classify, remediate</p>
        </div>
        <div className="flex items-center gap-3">
          {Object.keys(results).length > 0 && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-[#3E8635] font-bold">{passCount} pass</span>
              {failCount > 0 && <span className="text-[#C9190B] font-bold">{failCount} fail</span>}
            </div>
          )}
          <button onClick={runAll} disabled={running !== null}
            className="px-4 py-2 rounded text-sm font-bold text-white bg-[#EE0000] hover:bg-[#A30000] disabled:bg-[#333]">
            {running ? 'Running...' : 'Run All'}
          </button>
        </div>
      </div>

      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded border border-[#F0AB00]/30 bg-[#F0AB00]/10">
        <span className="text-[#F0AB00] text-xs font-bold uppercase tracking-wider">Ecosystem Only</span>
        <span className="text-[#6A6E73] text-xs">— all scenarios restricted to ecosystem namespaces</span>
      </div>

      <div className="space-y-4">
        {scenarios.map(scenario => {
          const result = results[scenario.id];
          const isRunning = running === scenario.id;
          const isExpanded = expanded === scenario.id;
          const statusColor = result ? (STATUS_COLORS[result.status] || '#6A6E73') : '#333';

          return (
            <div key={scenario.id} className="border rounded-xl overflow-hidden"
              style={{ borderColor: isExpanded ? statusColor : '#333', borderLeftWidth: '4px', borderLeftColor: statusColor }}>

              <div className="p-5 cursor-pointer hover:bg-[#1a1a1a] transition-colors"
                onClick={() => setExpanded(isExpanded ? null : scenario.id)}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    {result ? (
                      <span className="text-xs font-bold px-2 py-1 rounded"
                        style={{ backgroundColor: `${statusColor}20`, color: statusColor }}>
                        {result.status.toUpperCase()}
                      </span>
                    ) : (
                      <span className="text-xs px-2 py-1 rounded bg-[#212121] text-[#6A6E73]">NOT RUN</span>
                    )}
                    <span className="text-white font-semibold">{scenario.name}</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-[#212121] text-[#0071C5]">{scenario.namespace}</span>
                    <span className="text-xs text-[#6A6E73]">→ {scenario.expected_classification}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={(e) => { e.stopPropagation(); runScenario(scenario.id); }}
                      disabled={isRunning}
                      className="px-3 py-1.5 rounded text-xs font-bold text-white bg-[#EE0000] hover:bg-[#A30000] disabled:bg-[#333]">
                      {isRunning ? '⟳ Running...' : 'Run'}
                    </button>
                    <span className="text-[#6A6E73]">{isExpanded ? '▼' : '▶'}</span>
                  </div>
                </div>
                <p className="text-sm text-[#a0a0a0]">{scenario.description}</p>
              </div>

              {isExpanded && (
                <div className="border-t border-[#333] p-5 bg-[#0f0f0f] space-y-4">
                  {isRunning && (
                    <div className="flex items-center gap-3 text-sm text-[#F0AB00]">
                      <span className="animate-pulse">●</span>
                      Running scenario — injecting failure, waiting for pipeline...
                    </div>
                  )}

                  {result && (
                    <>
                      {/* Steps */}
                      <div>
                        <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">Pipeline Steps</div>
                        <div className="flex gap-2">
                          {result.steps.map((step, i) => (
                            <div key={i} className="flex items-center gap-2">
                              <div className={`px-3 py-1.5 rounded text-xs font-medium ${
                                step.status === 'ok' || step.status === 'done' ? 'bg-[#3E8635]/20 text-[#3E8635]' :
                                step.status === 'skipped' ? 'bg-[#212121] text-[#6A6E73]' :
                                'bg-[#C9190B]/20 text-[#C9190B]'
                              }`}>
                                {step.step}
                              </div>
                              {i < result.steps.length - 1 && <span className="text-[#6A6E73]">→</span>}
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* EDD Checks */}
                      {result.checks.length > 0 && (
                        <div>
                          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">
                            EDD Validation ({result.checks.filter(c => c.passed).length}/{result.checks.length} passed)
                          </div>
                          <div className="space-y-1">
                            {result.checks.map((check, i) => (
                              <div key={i} className="flex items-center gap-3 bg-[#1a1a1a] rounded px-3 py-2 text-xs">
                                <span className={`font-bold ${check.passed ? 'text-[#3E8635]' : 'text-[#C9190B]'}`}>
                                  {check.passed ? '✓' : '✗'}
                                </span>
                                <span className="text-white font-medium">{check.check.replace(/_/g, ' ')}</span>
                                <span className="text-[#6A6E73] flex-1">{check.detail}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {result.error && (
                        <div className="bg-[#C9190B]/10 border border-[#C9190B]/30 rounded p-3 text-xs text-[#C9190B]">
                          {result.error}
                        </div>
                      )}
                    </>
                  )}

                  {!result && !isRunning && (
                    <div className="text-sm text-[#6A6E73]">Click "Run" to execute this scenario</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
