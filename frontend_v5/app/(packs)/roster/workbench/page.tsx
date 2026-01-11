"use client";

import { useState, useEffect, useCallback } from "react";
import { Upload, Download, Play, Terminal, LayoutGrid, AlertCircle, Activity, ScrollText, Package, Settings, Home, ArrowLeft } from "lucide-react";
import Link from "next/link";

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

export default function RosterWorkbench() {
  const mounted = useMounted();

  // State
  const [tours, setTours] = useState<TourInput[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<ScheduleResponse | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeNav, setActiveNav] = useState("dashboard");
  const [optimizeMode, setOptimizeMode] = useState<"fast" | "deep">("fast");

  // Helpers
  const addLog = useCallback(
    (level: LogEntry["level"], message: string) => {
      const now = new Date();
      const timestamp = `${now.getMinutes().toString().padStart(2, "0")}:${now
        .getSeconds()
        .toString()
        .padStart(2, "0")}.${now.getMilliseconds().toString().padStart(3, "0")}`;
      setLogs((prev) => [...prev, { timestamp, level, message }]);
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
      const timeBudget = optimizeMode === "fast" ? 120 : 600;
      addLog("INFO", `Submitting optimization (${optimizeMode} mode, ${timeBudget}s budget)...`);

      const run = await createRun(tours, undefined, timeBudget);
      setRunId(run.run_id);
      addLog("OK", `Run created: ${run.run_id}`);
    } catch (err: any) {
      setError(`Start failed: ${err.message}`);
      addLog("ERROR", `Start failed: ${err.message}`);
      setIsRunning(false);
    }
  };

  // Polling Effect
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

        if (status.status === lastStatus) {
          statusUnchangedCount++;
        } else {
          statusUnchangedCount = 0;
          lastStatus = status.status;
        }

        if (status.status === "RUNNING") {
          const elapsedSec = Math.floor((Date.now() - startTime) / 1000);

          if (pollCount % 3 === 0) {
            const phaseMsg = status.phase || `Phase ${Math.min(Math.floor(pollCount / 3), 4)}`;
            addLog("SOLVER", `${phaseMsg}: Processing...`);
          }

          if (elapsedSec >= 60 && elapsedSec % 30 === 0) {
            addLog("WARN", `Still running after ${elapsedSec}s...`);
          }
        }

        if (status.status === "COMPLETED") {
          addLog("INFO", "[INFO] Fetching final result matrix...");

          let plan = null;
          let lastFetchError: Error | null = null;

          for (let attempt = 1; attempt <= 3; attempt++) {
            try {
              plan = await getRunResult(runId);
              break;
            } catch (fetchErr: any) {
              lastFetchError = fetchErr;
              if (attempt < 3) {
                addLog("WARN", `Fetch attempt ${attempt}/3 failed, retrying...`);
                await new Promise(r => setTimeout(r, 1000 * attempt));
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
            addLog("ERROR", `Failed to fetch result: ${lastFetchError?.message}`);
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

    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [runId, isRunning, addLog]);

  // Export Handler - Export both Roster CSV and KPI Insights CSV
  const handleExport = () => {
    if (!result) return;

    // Export 1: Roster CSV with shifts
    exportToCSV(result.assignments, `solvereign_v5_${result.id}`);

    // Export 2: KPI Insights CSV (triggered after small delay)
    setTimeout(() => {
      const stats = result.stats;
      const BOM = "\uFEFF";
      const SEPARATOR = ";";
      const LINE_END = "\r\n";

      const kpiContent = BOM +
        ["KPI", "Wert"].join(SEPARATOR) + LINE_END +
        ["Fahrer Gesamt", stats.total_drivers].join(SEPARATOR) + LINE_END +
        ["FTE Fahrer", stats.drivers_fte].join(SEPARATOR) + LINE_END +
        ["PT Fahrer", stats.drivers_pt].join(SEPARATOR) + LINE_END +
        ["Touren Eingabe", stats.total_tours_input].join(SEPARATOR) + LINE_END +
        ["Touren Zugewiesen", stats.total_tours_assigned].join(SEPARATOR) + LINE_END +
        ["Touren Nicht Zugewiesen", stats.total_tours_unassigned].join(SEPARATOR) + LINE_END +
        ["Zuweisungsrate (%)", (stats.assignment_rate * 100).toFixed(1)].join(SEPARATOR) + LINE_END +
        ["Durchschn. Auslastung (%)", (stats.average_driver_utilization * 100).toFixed(1)].join(SEPARATOR) + LINE_END +
        ["Durchschn. Arbeitsstunden", stats.average_work_hours?.toFixed(1) || "-"].join(SEPARATOR) + LINE_END +
        ["Blöcke 1er", stats.block_counts["1er"] || 0].join(SEPARATOR) + LINE_END +
        ["Blöcke 2er", stats.block_counts["2er"] || 0].join(SEPARATOR) + LINE_END +
        ["Blöcke 3er", stats.block_counts["3er"] || 0].join(SEPARATOR) + LINE_END +
        // Fleet Counter metrics (v7.2.0)
        ["Fahrzeuge Peak", stats.fleet_peak_count || 0].join(SEPARATOR) + LINE_END +
        ["Peak Tag", stats.fleet_peak_day || "N/A"].join(SEPARATOR) + LINE_END +
        ["Peak Zeit", stats.fleet_peak_time || "N/A"].join(SEPARATOR) + LINE_END;

      const blob = new Blob([kpiContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `solvereign_v5_${result.id}_kpis.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }, 500);

    addLog("OK", "Export Pack: Roster CSV + KPI Insights CSV generated.");
  };

  // Derived Data
  const driverRows: DriverRow[] = result
    ? assignmentsToDriverRows(result.assignments)
    : [];

  // SSR Guard
  if (!mounted) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="animate-pulse text-slate-500">Loading...</div>
      </div>
    );
  }

  const navItems = [
    { id: "dashboard", icon: LayoutGrid, label: "Runs Overview" },
    { id: "detail", icon: Activity, label: "Run Detail", href: runId ? `/runs/${runId}` : undefined },
    { id: "matrix", icon: LayoutGrid, label: "Roster Matrix", href: runId ? `/runs/${runId}` : undefined },
    { id: "logs", icon: ScrollText, label: "System Logs" },
    { id: "artifacts", icon: Package, label: "Artifacts" },
  ];

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex">
      {/* Sidebar */}
      <aside className="w-56 bg-slate-800/50 border-r border-slate-700/50 flex flex-col">
        {/* Logo */}
        <div className="p-5 border-b border-slate-700/50">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
              <span className="text-white font-bold text-sm">R</span>
            </div>
            <div>
              <h1 className="text-base font-bold text-white">Roster Pack</h1>
              <p className="text-[10px] text-slate-500 font-mono">SOLVEREIGN</p>
            </div>
          </div>
        </div>

        {/* Back to Platform */}
        <div className="p-3 border-b border-slate-700/50">
          <Link
            href="/platform/home"
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-400 hover:bg-slate-700/50 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Platform
          </Link>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => (
            item.href ? (
              <Link
                key={item.id}
                href={item.href}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${activeNav === item.id
                  ? "bg-amber-600/20 text-amber-400"
                  : "text-slate-400 hover:bg-slate-700/50 hover:text-slate-200"
                  }`}
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </Link>
            ) : (
              <button
                key={item.id}
                onClick={() => setActiveNav(item.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${activeNav === item.id
                  ? "bg-amber-600/20 text-amber-400"
                  : "text-slate-400 hover:bg-slate-700/50 hover:text-slate-200"
                  }`}
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </button>
            )
          ))}
        </nav>

        {/* Config */}
        <div className="p-3 border-t border-slate-700/50">
          <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-500 hover:bg-slate-700/50 hover:text-slate-400 transition-colors">
            <Settings className="w-4 h-4" />
            Config (Read-Only)
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="h-14 border-b border-slate-700/50 flex items-center justify-between px-6 bg-slate-800/30">
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-slate-300">Workbench</span>
            <div className={`px-2.5 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 ${isRunning
              ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
              : result
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                : "bg-slate-700/50 text-slate-400 border border-slate-600"
              }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${isRunning ? "bg-blue-400 animate-pulse" : result ? "bg-emerald-400" : "bg-slate-500"
                }`} />
              {isRunning ? "Running" : result ? "Completed" : "Ready"}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex bg-slate-700/50 rounded-lg p-1 mr-2 border border-slate-600">
              <button
                onClick={() => setOptimizeMode("fast")}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${optimizeMode === "fast"
                  ? "bg-slate-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-300"
                  }`}
                title="120s Budget - Good for quick iteration"
              >
                Fast (120s)
              </button>
              <button
                onClick={() => setOptimizeMode("deep")}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${optimizeMode === "deep"
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-300"
                  }`}
                title="600s Budget - Production quality"
              >
                Deep (600s)
              </button>
            </div>
            <label className="cursor-pointer">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-700/50 hover:bg-slate-600/50 border border-slate-600 rounded-lg text-xs text-slate-300 transition-colors">
                <Upload className="w-3.5 h-3.5" />
                Upload CSV
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
              className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-xs font-medium text-white transition-colors"
            >
              <Play className="w-3.5 h-3.5" />
              {isRunning ? "Running..." : "Optimize"}
            </button>

            {result && (
              <button
                onClick={handleExport}
                className="flex items-center gap-2 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-xs font-medium text-white transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                Export Pack
              </button>
            )}
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

            {/* Input Stats */}
            {tours.length > 0 && (
              <div className="flex items-center gap-6 text-sm">
                <span className="text-slate-500">Input:</span>
                <span className="text-slate-300 font-mono tabular-nums">{tours.length} Tours</span>
                {runId && (
                  <>
                    <span className="text-slate-500">Run ID:</span>
                    <span className="text-slate-300 font-mono">{runId.slice(0, 8)}</span>
                  </>
                )}
              </div>
            )}

            {/* KPI Cards */}
            <KPICards
              driversFTE={result?.stats.drivers_fte ?? 0}
              driversPT={result?.stats.drivers_pt ?? 0}
              utilization={result?.stats.average_driver_utilization ?? 0}
              gapToLB={0}
              totalHours={result?.stats.total_hours ?? 0}
              fleetPeakCount={result?.stats.fleet_peak_count ?? 0}
              fleetPeakDay={result?.stats.fleet_peak_day ?? ""}
              fleetPeakTime={result?.stats.fleet_peak_time ?? ""}
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

            {/* Getting Started */}
            {!result && (
              <div className="mt-8 p-4 border border-dashed border-slate-700 rounded-lg text-center">
                <p className="text-sm text-slate-500 mb-2">Upload a CSV file and click Optimize to start</p>
                <div
                  className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 rounded-lg text-sm text-slate-400"
                >
                  <Activity className="w-4 h-4" />
                  Ready to optimize
                </div>
              </div>
            )}
          </div>

          {/* Right Panel - Live Console */}
          <div className="w-72 border-l border-slate-700/50 flex flex-col bg-slate-800/20">
            <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
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
