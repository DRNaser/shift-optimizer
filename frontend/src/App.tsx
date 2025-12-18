import { useState, useCallback } from 'react';
import './index.css';
import type { ScheduleRequest, ScheduleResponse, TourInput } from './api';
import { createSchedule, connectLogStream } from './api';
import { parseForecastCSV } from './utils/csvParser';
import { exportRosterCSV, exportSolverProofCSV, exportUnassignedCSV } from './utils/exportCSV';
import { FileUpload } from './components/FileUpload';
import { LogTerminal } from './components/LogTerminal';
import { HealthWidget } from './components/HealthWidget';
import { StatsGrid } from './components/StatsGrid';
import { ScheduleGrid } from './components/ScheduleGrid';
import { UnassignedList } from './components/UnassignedList';
import { SolverProof } from './components/SolverProof';
import { LeftoverTours } from './components/LeftoverTours';

type SolverType = 'greedy' | 'cpsat' | 'cpsat+lns' | 'cpsat-global' | 'set-partitioning' | 'heuristic';
type AppView = 'setup' | 'running' | 'results';
type ResultsTab = 'schedule' | 'proof' | 'leftover';

export default function App() {
  // State
  const [view, setView] = useState<AppView>('setup');
  const [tours, setTours] = useState<TourInput[]>([]);
  const [parseErrors, setParseErrors] = useState<string[]>([]);
  const [weekStart, setWeekStart] = useState('');
  const [fileName, setFileName] = useState('');

  // Config
  // Config
  const [solverType, setSolverType] = useState<SolverType>('cpsat');
  const [timeLimit, setTimeLimit] = useState(30);
  const [seed, setSeed] = useState(42);
  const [targetFtes, setTargetFtes] = useState(145);
  const [overflowCap, setOverflowCap] = useState(10);

  // Execution
  const [logs, setLogs] = useState<string[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Results
  const [result, setResult] = useState<ScheduleResponse | null>(null);
  const [resultsTab, setResultsTab] = useState<ResultsTab>('schedule');

  // File upload handler
  const handleFileSelect = useCallback((content: string, name: string) => {
    const parsed = parseForecastCSV(content);
    setTours(parsed.tours);
    setParseErrors(parsed.errors);
    setWeekStart(parsed.weekStart);
    setFileName(name);
  }, []);

  // Run solver
  const handleRunSolver = useCallback(async () => {
    if (tours.length === 0) return;

    setView('running');
    setIsRunning(true);
    setError(null);
    setLogs([]);
    setResult(null);

    // Connect to log stream
    const MAX_LOG_LINES = 5000;
    const es = connectLogStream((msg) => {
      setLogs((prev) => {
        const updated = [...prev, msg];
        // Ring buffer: keep only last MAX_LOG_LINES
        return updated.length > MAX_LOG_LINES ? updated.slice(-MAX_LOG_LINES) : updated;
      });
    });
    // Note: onopen/onerror handlers are set in connectLogStream with debug logging
    // Just track connection state here without overwriting
    const originalOnOpen = es.onopen;
    const originalOnError = es.onerror;
    es.onopen = (e) => {
      if (originalOnOpen) (originalOnOpen as (e: Event) => void)(e);
      setIsConnected(true);
    };
    es.onerror = (e) => {
      if (originalOnError) (originalOnError as (e: Event) => void)(e);
      setIsConnected(false);
    };

    try {
      const request: ScheduleRequest = {
        week_start: weekStart,
        tours,
        solver_type: solverType,
        time_limit_seconds: timeLimit,
        seed,
        lns_iterations: solverType === 'cpsat+lns' ? 100 : undefined,
        target_ftes: solverType === 'heuristic' ? targetFtes : undefined,
        fte_overflow_cap: solverType === 'heuristic' ? overflowCap : undefined,
      };

      const response = await createSchedule(request);
      setResult(response);
      setView('results');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
      setView('setup');
    } finally {
      es.close();
      setIsConnected(false);
      setIsRunning(false);
    }
  }, [tours, weekStart, solverType, timeLimit, seed]);

  // Reset to setup
  const handleReset = () => {
    setView('setup');
    setResult(null);
    setLogs([]);
  };

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="app-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
          Shift Optimizer
        </div>
        <div className="flex gap-sm items-center">
          {view === 'results' && (
            <button className="btn btn-secondary" onClick={handleReset}>
              ← New Plan
            </button>
          )}
          <span className="badge badge-info">v4.0</span>
        </div>
      </header>

      <main className="app-main">
        {/* Sidebar */}
        <aside className="sidebar" style={{ padding: 'var(--spacing-lg)', display: 'flex', flexDirection: 'column', gap: 'var(--spacing-md)' }}>
          <HealthWidget />

          {view === 'setup' && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">⚡ Configuration</span>
              </div>
              <div className="form-group">
                <label className="form-label">Solver</label>
                <select
                  className="form-select"
                  value={solverType}
                  onChange={(e) => setSolverType(e.target.value as SolverType)}
                >
                  <option value="greedy">Greedy (Fast)</option>
                  <option value="heuristic">Heuristic (Target FTE)</option>
                  <option value="cpsat">CP-SAT (Optimal)</option>
                  <option value="cpsat+lns">CP-SAT + LNS (Best)</option>
                  <option value="cpsat-global">CP-SAT Global FTE (No PT)</option>
                  <option value="set-partitioning">Set-Partitioning (Crew)</option>
                </select>
              </div>

              {solverType === 'heuristic' && (
                <>
                  <div className="form-group">
                    <label className="form-label">Target FTEs</label>
                    <input
                      type="number"
                      className="form-input"
                      value={targetFtes}
                      onChange={(e) => setTargetFtes(Number(e.target.value))}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Overflow Cap</label>
                    <input
                      type="number"
                      className="form-input"
                      value={overflowCap}
                      onChange={(e) => setOverflowCap(Number(e.target.value))}
                    />
                  </div>
                </>
              )}
              <div className="form-group">
                <label className="form-label">Time Limit (seconds)</label>
                <input
                  type="number"
                  className="form-input"
                  value={timeLimit}
                  onChange={(e) => setTimeLimit(Number(e.target.value))}
                  min={5}
                  max={300}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Seed</label>
                <input
                  type="number"
                  className="form-input"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                />
              </div>
            </div>
          )}
        </aside>

        {/* Content */}
        <section className="content">
          {/* SETUP VIEW */}
          {view === 'setup' && (
            <div style={{ maxWidth: '800px', margin: '0 auto' }}>
              <h1 style={{ fontSize: '1.5rem', marginBottom: 'var(--spacing-lg)' }}>📤 Upload Forecast Data</h1>

              <FileUpload onFileSelect={handleFileSelect} />

              {parseErrors.length > 0 && (
                <div className="card mt-md" style={{ borderColor: 'var(--color-error)' }}>
                  <div className="card-header">
                    <span className="card-title text-error">Parse Errors</span>
                  </div>
                  <ul style={{ paddingLeft: 'var(--spacing-lg)' }}>
                    {parseErrors.map((err, i) => (
                      <li key={i} className="text-muted">{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              {tours.length > 0 && (
                <div className="card mt-md">
                  <div className="card-header">
                    <span className="card-title">✓ {fileName}</span>
                    <span className="badge badge-success">{tours.length} tours loaded</span>
                  </div>
                  <p className="text-muted">Week starting: {weekStart}</p>
                  <button
                    className="btn btn-primary btn-lg mt-md"
                    onClick={handleRunSolver}
                    disabled={isRunning}
                    style={{ width: '100%' }}
                  >
                    {isRunning ? <><div className="spinner"></div> Running...</> : '🚀 Optimize Schedule'}
                  </button>
                </div>
              )}

              {error && (
                <div className="card mt-md" style={{ borderColor: 'var(--color-error)' }}>
                  <div className="card-header">
                    <span className="card-title text-error">Error</span>
                  </div>
                  <p>{error}</p>
                </div>
              )}
            </div>
          )}

          {/* RUNNING VIEW */}
          {view === 'running' && (
            <div style={{ maxWidth: '900px', margin: '0 auto' }}>
              <div className="flex items-center justify-between mb-md">
                <h1 style={{ fontSize: '1.5rem' }}>⏳ Solving...</h1>
                <span className="badge badge-warning">
                  {solverType.toUpperCase()} | {timeLimit}s limit
                </span>
              </div>
              <LogTerminal logs={logs} isConnected={isConnected} />
            </div>
          )}

          {/* RESULTS VIEW */}
          {view === 'results' && result && (
            <div>
              <div className="flex items-center justify-between mb-lg">
                <h1 style={{ fontSize: '1.5rem' }}>📊 Optimization Results</h1>
                <div className="flex gap-sm">
                  <button className="btn btn-secondary" onClick={() => exportRosterCSV(result)}>
                    📥 Roster CSV
                  </button>
                  <button className="btn btn-secondary" onClick={() => exportSolverProofCSV(tours, result)}>
                    📥 Nachweis CSV
                  </button>
                  <button className="btn btn-secondary" onClick={() => exportUnassignedCSV(tours, result)}>
                    📥 Resttouren CSV
                  </button>
                </div>
              </div>

              <StatsGrid stats={result.stats} />

              {/* Tabs */}
              <div style={{ display: 'flex', gap: 'var(--spacing-sm)', margin: 'var(--spacing-xl) 0 var(--spacing-md)', borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--spacing-sm)' }}>
                <button
                  className={`btn ${resultsTab === 'schedule' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setResultsTab('schedule')}
                >
                  📅 Dienstplan
                </button>
                <button
                  className={`btn ${resultsTab === 'proof' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setResultsTab('proof')}
                >
                  🔍 Solver-Nachweis
                </button>
                <button
                  className={`btn ${resultsTab === 'leftover' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setResultsTab('leftover')}
                >
                  ⚠️ Resttouren
                </button>
              </div>

              {/* Tab Content */}
              {resultsTab === 'schedule' && (
                <>
                  <ScheduleGrid assignments={result.assignments} />
                  <div style={{ marginTop: 'var(--spacing-xl)' }}>
                    <UnassignedList tours={result.unassigned_tours} />
                  </div>
                </>
              )}

              {resultsTab === 'proof' && (
                <SolverProof inputTours={tours} response={result} />
              )}

              {resultsTab === 'leftover' && (
                <LeftoverTours inputTours={tours} response={result} />
              )}

              {result.validation.warnings.length > 0 && (
                <div className="card mt-lg">
                  <div className="card-header">
                    <span className="card-title">⚠️ Warnings</span>
                  </div>
                  <ul style={{ paddingLeft: 'var(--spacing-lg)' }}>
                    {result.validation.warnings.map((w, i) => (
                      <li key={i} className="text-warning">{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
