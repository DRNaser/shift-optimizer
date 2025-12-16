// SHIFT OPTIMIZER - Main App
// React frontend for the weekly shift optimizer

import React, { useState, useCallback } from 'react';
import {
  TourInput,
  DriverInput,
  ScheduleResponse,
  ApiError,
  SolverType
} from './types';
import Header from './components/Header';
import QuickDataEntry from './components/QuickDataEntry';
import SolverOptions from './components/SolverOptions';
import WeekOverview from './components/WeekOverview';
import UnassignedTours from './components/UnassignedTours';
import StatsDashboard from './components/StatsDashboard';
import ExportButton from './components/ExportButton';
import RosterMatrix from './components/RosterMatrix';
import { createSchedule } from './services/api';
import { LoadingIcon } from './components/Icons';

function App() {
  // Data state
  const [tours, setTours] = useState<TourInput[]>([]);
  const [drivers, setDrivers] = useState<DriverInput[]>([]);

  // Solver options
  const [solverType, setSolverType] = useState<SolverType>('cpsat');
  const [timeLimit, setTimeLimit] = useState(30);
  const [lnsIterations, setLnsIterations] = useState(10);

  // Results state
  const [result, setResult] = useState<ScheduleResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Handle data load from QuickDataEntry
  const handleDataLoad = useCallback((newTours: TourInput[], newDrivers: DriverInput[]) => {
    setTours(newTours);
    setDrivers(newDrivers);
    setResult(null);
    setError(null);
  }, []);

  // Get current Monday for week_start
  const getWeekStart = (): string => {
    const today = new Date();
    const day = today.getDay();
    const diff = today.getDate() - day + (day === 0 ? -6 : 1);
    const monday = new Date(today.setDate(diff));
    return monday.toISOString().split('T')[0];
  };

  // Run optimization
  const handleOptimize = useCallback(async () => {
    if (tours.length === 0 || drivers.length === 0) {
      setError({
        status: 'error',
        message: 'No data loaded',
        details: ['Please load tours and drivers data first.'],
      });
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await createSchedule({
        tours,
        drivers,
        week_start: getWeekStart(),
        solver_type: solverType,
        time_limit_seconds: timeLimit,
        lns_iterations: lnsIterations,
        prefer_larger_blocks: true,
      });
      setResult(response);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setIsLoading(false);
    }
  }, [tours, drivers, solverType, timeLimit, lnsIterations]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-slate-200 font-sans text-slate-800">
      <Header />

      <main className="container mx-auto px-4 py-8 max-w-7xl">
        {/* Setup Section */}
        <section className="mb-8">
          <div className="grid md:grid-cols-2 gap-6">
            <QuickDataEntry onDataLoad={handleDataLoad} />
            <SolverOptions
              solverType={solverType}
              onSolverTypeChange={setSolverType}
              timeLimit={timeLimit}
              onTimeLimitChange={setTimeLimit}
              lnsIterations={lnsIterations}
              onLnsIterationsChange={setLnsIterations}
              isLoading={isLoading}
            />
          </div>
        </section>

        {/* Data Summary */}
        {tours.length > 0 && (
          <section className="mb-8">
            <div className="bg-white rounded-xl shadow p-4 flex items-center justify-between">
              <div className="flex items-center gap-6">
                <div className="flex items-center gap-2">
                  <span className="text-2xl">📦</span>
                  <div>
                    <div className="text-2xl font-bold text-gray-900">{tours.length}</div>
                    <div className="text-sm text-gray-500">Tours</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-2xl">👤</span>
                  <div>
                    <div className="text-2xl font-bold text-gray-900">{drivers.length}</div>
                    <div className="text-sm text-gray-500">Drivers</div>
                  </div>
                </div>
              </div>

              <button
                onClick={handleOptimize}
                disabled={isLoading || tours.length === 0}
                className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-bold py-3 px-8 rounded-xl shadow-lg hover:from-indigo-700 hover:to-purple-700 disabled:from-slate-400 disabled:to-slate-400 disabled:cursor-not-allowed transition-all duration-300 transform hover:scale-105 flex items-center gap-2"
              >
                {isLoading ? (
                  <>
                    <LoadingIcon />
                    Optimizing...
                  </>
                ) : (
                  <>
                    ⚡ Optimize Schedule
                  </>
                )}
              </button>
            </div>
          </section>
        )}

        {/* Error Display */}
        {error && (
          <section className="mb-8">
            <div className="bg-red-50 border-l-4 border-red-500 text-red-700 p-4 rounded-xl shadow" role="alert">
              <p className="font-bold text-lg">Error: {error.message}</p>
              {error.details.length > 0 && (
                <ul className="mt-2 list-disc list-inside">
                  {error.details.map((detail, index) => (
                    <li key={index}>{detail}</li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}

        {/* Results */}
        {result && (
          <>
            {/* Stats Dashboard */}
            <section className="mb-8">
              <div className="flex items-center justify-between mb-4">
                <div className="flex-1">
                  <StatsDashboard
                    stats={result.stats}
                    validation={result.validation}
                    solverType={result.solver_type}
                  />
                </div>
                <div className="ml-4">
                  <ExportButton schedule={result} />
                </div>
              </div>
            </section>

            {/* Week Overview Grid */}
            <section className="mb-8">
              <WeekOverview schedule={result} />
            </section>

            {/* Unassigned Tours */}
            <section className="mb-8">
              <UnassignedTours tours={result.unassigned_tours} />
            </section>

            {/* Roster Matrix */}
            <section className="mb-8">
              <RosterMatrix schedule={result} />
            </section>
          </>
        )}

        {/* Empty State */}
        {!result && !error && tours.length === 0 && (
          <section className="text-center py-20">
            <div className="text-6xl mb-4">📅</div>
            <h2 className="text-2xl font-bold text-gray-700 mb-2">
              Welcome to Shift Optimizer
            </h2>
            <p className="text-gray-500 max-w-md mx-auto">
              Load tour and driver data using the panel above, then click "Optimize Schedule"
              to generate an optimal weekly assignment.
            </p>
          </section>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200 mt-12 py-6 text-center text-gray-500 text-sm">
        Shift Optimizer v2.0 • Powered by OR-Tools CP-SAT
      </footer>
    </div>
  );
}

export default App;
