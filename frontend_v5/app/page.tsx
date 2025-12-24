"use client";

import { useState, useEffect, useCallback } from "react";
import { Upload, Download, Play, Terminal, LayoutGrid, AlertCircle } from "lucide-react";

import { useMounted } from "@/lib/hooks/use-mounted";
import { LiveConsole, type LogEntry } from "@/components/ui/live-console";
import { KPICards } from "@/components/ui/kpi-cards";
import { MatrixView, type DriverRow } from "@/components/ui/matrix-view";
import { exportToCSV, assignmentsToDriverRows } from "@/lib/export";
import {
  createRun,
  getRunStatus,
  getRunResult,
  parseCSV,
  type ScheduleResponse,
  type TourInput,
} from "@/lib/api";

export default function Home() {
  const mounted = useMounted();

  // State
  const [tours, setTours] = useState<TourInput[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<ScheduleResponse | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Helpers
  const addLog = useCallback(
    (level: LogEntry["level"], message: string) => {
      const now = new Date();
      // v5 MONITORING: Millisecond precision timestamp
      const timestamp = `${now.getMinutes().toString().padStart(2, "0")}:${now
        .getSeconds()
        .toString()
        .padStart(2, "0")}.${now.getMilliseconds().toString().padStart(3, "0")}`;
      setLogs((prev) => [...prev, { timestamp, level, message }]); // ACCUMULATE, never replace
    },
    []
  );

  // File Upload Handler
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const content = await file.text();
      const parsedTours = parseCSV(content);
      setTours(parsedTours);
      setResult(null);
      setError(null);
      addLog("OK", `Matrix Parser: ${parsedTours.length} tours detected.`);
    } catch (err: any) {
      setError(`Parse error: ${err.message}`);
      addLog("ERROR", `Parse failed: ${err.message}`);
    }
  };

  // Start Optimization
  const handleOptimize = async () => {
    if (tours.length === 0) {
      setError("No tours loaded. Please upload a CSV file first.");
      return;
    }

    try {
      setError(null);
      setIsRunning(true);
      addLog("INFO", "Submitting optimization request...");

      const run = await createRun(tours);
      setRunId(run.run_id);
      addLog("OK", `Run created: ${run.run_id}`);
    } catch (err: any) {
      setError(`Start failed: ${err.message}`);
      addLog("ERROR", `Start failed: ${err.message}`);
      setIsRunning(false);
    }
  };

  // Polling Effect - Robust with timeout warning and auto-result fetch
  useEffect(() => {
    if (!runId || !isRunning) return;

    let pollCount = 0;
    let lastStatus = "QUEUED";
    let statusUnchangedCount = 0;
    const startTime = Date.now();

    const poll = async () => {
      try {
        const status = await getRunStatus(runId);
        pollCount++;

        // Track if status changed
        if (status.status === lastStatus) {
          statusUnchangedCount++;
        } else {
          statusUnchangedCount = 0;
          lastStatus = status.status;
        }

        // Phase logging - accumulate, don't replace
        if (status.status === "RUNNING") {
          const elapsedSec = Math.floor((Date.now() - startTime) / 1000);

          // Log phase updates (every 3 polls = 6s)
          if (pollCount % 3 === 0) {
            const phaseMsg = status.phase || `Phase ${Math.min(Math.floor(pollCount / 3), 4)}`;
            addLog("SOLVER", `${phaseMsg}: Processing...`);
          }

          // Timeout warning after 60s
          if (elapsedSec >= 60 && elapsedSec % 30 === 0) {
            addLog("WARN", `Still running after ${elapsedSec}s... (This is normal for large instances)`);
          }
        }

        // Terminal states - ONLY clear interval here
        if (status.status === "COMPLETED") {
          addLog("INFO", "[INFO] Fetching final result matrix...");

          // Retry with exponential backoff (max 3 attempts)
          let plan = null;
          let lastFetchError: Error | null = null;

          for (let attempt = 1; attempt <= 3; attempt++) {
            try {
              plan = await getRunResult(runId);
              break; // Success
            } catch (fetchErr: any) {
              lastFetchError = fetchErr;
              if (attempt < 3) {
                addLog("WARN", `Fetch attempt ${attempt}/3 failed, retrying in ${attempt}s...`);
                await new Promise(r => setTimeout(r, 1000 * attempt)); // 1s, 2s backoff
              }
            }
          }

          if (plan) {
            setResult(plan);
            setIsRunning(false);

            const gapToLB = plan.stats.average_driver_utilization > 0.9 ? 0 : 0.05;
            addLog(
              "FINAL",
              `✓ Optimal Solution. Drivers: ${plan.stats.total_drivers}, Gap: ${(gapToLB * 100).toFixed(1)}%`
            );
          } else {
            addLog("ERROR", `Failed to fetch result after 3 attempts: ${lastFetchError?.message}`);
            setError(`Result fetch failed: ${lastFetchError?.message}`);
            setIsRunning(false);
          }
        } else if (status.status === "FAILED" || status.status === "CANCELLED") {
          addLog("ERROR", `✗ Run ${status.status}`);
          setIsRunning(false);
          setError(`Run ${status.status}`);
        }
      } catch (err: any) {
        console.error("[Poll error]", err);
        addLog("ERROR", `Poll error: ${err.message}`);
      }
    };

    // Initial poll
    poll();

    // Poll every 2s
    const interval = setInterval(poll, 2000);

    // CRITICAL: Only clear interval when isRunning becomes false
    return () => clearInterval(interval);
  }, [runId, isRunning, addLog]);

  // Export Handler
  const handleExport = () => {
    if (!result) return;
    exportToCSV(result.assignments, `solvereign_v5_${result.id}`);
    addLog("OK", "Master Export generated successfully.");
  };

  // Derived Data
  const driverRows: DriverRow[] = result
    ? assignmentsToDriverRows(result.assignments)
    : [];

  // SSR Guard
  if (!mounted) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="animate-pulse text-slate-500">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col">
        {/* Logo */}
        <div className="p-6 border-b border-slate-800">
          <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
            Solvereign
          </h1>
          <p className="text-xs text-slate-500 mt-1">Professional v5</p>
        </div>

        {/* Status Badge */}
        <div className="p-4">
          <div
            className={`px-3 py-2 rounded-lg text-xs font-medium flex items-center gap-2 ${isRunning
              ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
              : result
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                : "bg-slate-800 text-slate-400 border border-slate-700"
              }`}
          >
            <div
              className={`w-2 h-2 rounded-full ${isRunning
                ? "bg-blue-400 animate-pulse"
                : result
                  ? "bg-emerald-400"
                  : "bg-slate-500"
                }`}
            />
            {isRunning ? "Engine Running" : result ? "v5 Optimal" : "System Ready"}
          </div>
        </div>

        {/* Actions */}
        <div className="p-4 space-y-3">
          <label className="block">
            <div className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg cursor-pointer transition-colors text-sm">
              <Upload className="w-4 h-4 text-slate-400" />
              <span>Upload CSV</span>
            </div>
            <input
              type="file"
              accept=".csv,.txt"
              onChange={handleFileUpload}
              className="hidden"
            />
          </label>

          <button
            onClick={handleOptimize}
            disabled={tours.length === 0 || isRunning}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
          >
            <Play className="w-4 h-4" />
            {isRunning ? "Running..." : "Optimize"}
          </button>

          {result && (
            <button
              onClick={handleExport}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-medium transition-colors"
            >
              <Download className="w-4 h-4" />
              Master Export
            </button>
          )}
        </div>

        {/* Stats */}
        {tours.length > 0 && (
          <div className="p-4 border-t border-slate-800 mt-auto">
            <p className="text-xs text-slate-500">Input</p>
            <p className="text-lg font-bold text-slate-300">{tours.length} Tours</p>
          </div>
        )}
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="h-14 border-b border-slate-800 flex items-center px-6 bg-slate-900/50">
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <LayoutGrid className="w-4 h-4" />
            <span>Dashboard</span>
          </div>
        </header>

        {/* Content Area */}
        <div className="flex-1 flex overflow-hidden">
          {/* Dashboard */}
          <div className="flex-1 p-6 overflow-y-auto space-y-6">
            {/* Error Alert */}
            {error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 flex items-center gap-3 text-red-400">
                <AlertCircle className="w-5 h-5 shrink-0" />
                <p className="text-sm">{error}</p>
              </div>
            )}

            {/* KPI Cards */}
            <KPICards
              driversFTE={result?.stats.drivers_fte ?? 0}
              driversPT={result?.stats.drivers_pt ?? 0}
              utilization={result?.stats.average_driver_utilization ?? 0}
              gapToLB={0} // TODO: Get from backend
              totalHours={result?.stats.total_hours ?? 0}
              isLoading={isRunning}
            />

            {/* Matrix View */}
            <div>
              <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
                <LayoutGrid className="w-5 h-5 text-slate-500" />
                Roster Matrix
              </h2>
              <MatrixView data={driverRows} />
            </div>
          </div>

          {/* Right Panel - Live Console */}
          <div className="w-80 border-l border-slate-800 flex flex-col bg-slate-900/30">
            <div className="p-3 border-b border-slate-800 flex items-center gap-2">
              <Terminal className="w-4 h-4 text-slate-500" />
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Live Console
              </span>
            </div>
            <div className="flex-1 overflow-hidden">
              <LiveConsole logs={logs} isRunning={isRunning} />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
