"use client";

import { useState, useEffect, useRef } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
    Download,
    LayoutGrid,
    ScrollText,
    ArrowLeft,
    CheckCircle2,
    Zap,
    Search,
    TrendingDown,
    RefreshCw,
    Activity
} from "lucide-react";
import { RosterMatrix } from "@/components/domain/roster-matrix";
import { PipelineStepper, getDefaultPipelineSteps } from "@/components/domain/pipeline-stepper";
import { exportRosterToCSV, exportInsightsToCSV, exportRunPackage } from "@/lib/export-utils";
import { RunDetailData } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useEventStream, getPhaseDisplayName, formatElapsed } from "@/lib/hooks/useEventStream";

interface RunDetailClientProps {
    runData: RunDetailData;
}

// KPI Card Component - Dark Theme
function KPICard({
    label,
    value,
    sublabel,
    variant = "default",
}: {
    label: string;
    value: string | number;
    sublabel?: string;
    variant?: "default" | "success" | "warning" | "danger";
}) {
    const variants = {
        default: "bg-slate-800/50 border-slate-700",
        success: "bg-emerald-500/10 border-emerald-500/30",
        warning: "bg-amber-500/10 border-amber-500/30",
        danger: "bg-red-500/10 border-red-500/30",
    };

    const sublabelVariants = {
        default: "text-slate-500",
        success: "text-emerald-400",
        warning: "text-amber-400",
        danger: "text-red-400",
    };

    return (
        <div className={cn("border rounded-lg p-4", variants[variant])}>
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">{label}</div>
            <div className="text-2xl font-bold text-white tabular-nums mt-1">{value}</div>
            {sublabel && (
                <div className={cn("text-xs mt-1", sublabelVariants[variant])}>{sublabel}</div>
            )}
        </div>
    );
}

// Insights Panel - Shows insights from RunInsights data
function InsightsPanel({ insights, violationCount }: { insights: RunDetailData['insights'], violationCount: number }) {
    const insightItems = [];

    if (violationCount === 0) {
        insightItems.push({
            type: "success",
            icon: CheckCircle2,
            title: "Feasibility Achieved",
            description: "u_sum = 0. No constraints violated."
        });
    } else {
        insightItems.push({
            type: "danger",
            icon: Zap,
            title: `${violationCount} Violations`,
            description: "Review constraint violations in logs."
        });
    }

    if (insights.orphans_count > 0) {
        insightItems.push({
            type: "warning",
            icon: TrendingDown,
            title: `${insights.orphans_count} Orphan Tours`,
            description: "Some tours could not be assigned to drivers."
        });
    }

    if (insights.core_share < 20 && insights.core_share > 0) {
        insightItems.push({
            type: "success",
            icon: CheckCircle2,
            title: "PT Share Target Met",
            description: `Core PT share: ${insights.core_share.toFixed(1)}% (Target < 20%)`
        });
    }

    const typeStyles = {
        info: "border-l-blue-500 bg-blue-500/5",
        warning: "border-l-amber-500 bg-amber-500/5",
        success: "border-l-emerald-500 bg-emerald-500/5",
        danger: "border-l-red-500 bg-red-500/5",
    };

    const iconStyles = {
        info: "text-blue-400",
        warning: "text-amber-400",
        success: "text-emerald-400",
        danger: "text-red-400",
    };

    return (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700 flex items-center gap-2">
                <Search className="w-4 h-4 text-slate-500" />
                <h3 className="text-sm font-semibold text-slate-200">Run Summary</h3>
            </div>
            <div className="divide-y divide-slate-700/50">
                {insightItems.length > 0 ? insightItems.map((insight, idx) => (
                    <div
                        key={idx}
                        className={cn("px-4 py-3 border-l-4", typeStyles[insight.type as keyof typeof typeStyles])}
                    >
                        <div className="flex items-start gap-2">
                            <insight.icon className={cn(
                                "w-4 h-4 mt-0.5 flex-shrink-0",
                                iconStyles[insight.type as keyof typeof iconStyles]
                            )} />
                            <div>
                                <div className="text-sm font-medium text-slate-200">{insight.title}</div>
                                <div className="text-xs text-slate-500 mt-0.5">{insight.description}</div>
                            </div>
                        </div>
                    </div>
                )) : (
                    <div className="p-4 text-sm text-slate-500 italic text-center">No insights available yet.</div>
                )}
            </div>
        </div>
    );
}

// NEW: Live RMP Rounds Table
function RmpRoundsTable({ events }: { events: any[] }) {
    // Filter and parse rmp_round events, reverse chronology
    const rounds = events
        .filter(e => e.event_type === "rmp_round" && e.metrics)
        .map(e => ({
            round: e.metrics.round,
            pool: e.metrics.pool_size,
            drivers: e.metrics.drivers_total,
            fte: e.metrics.drivers_fte,
            pt: e.metrics.drivers_pt,
            uncovered: e.metrics.uncovered,
            quality: e.metrics.pool_quality_pct,
            ts: e.ts.split('T')[1].slice(0, 8)
        }))
        .reverse();

    if (rounds.length === 0) return null;

    return (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden mt-4">
            <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <RefreshCw className="w-4 h-4 text-slate-500" />
                    <h3 className="text-sm font-semibold text-slate-200">Set-Partitioning Rounds</h3>
                </div>
                <span className="text-xs text-slate-500">{rounds.length} rounds logged</span>
            </div>
            <div className="overflow-x-auto max-h-[300px]">
                <table className="w-full text-left text-xs text-slate-400">
                    <thead className="bg-slate-900/50 text-slate-300 sticky top-0">
                        <tr>
                            <th className="px-4 py-2 font-medium">Time</th>
                            <th className="px-4 py-2 font-medium">Round</th>
                            <th className="px-4 py-2 font-medium">Pool Size</th>
                            <th className="px-4 py-2 font-medium">Drivers (Total)</th>
                            <th className="px-4 py-2 font-medium">FTE / PT</th>
                            <th className="px-4 py-2 font-medium text-right">Coverage Quality</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/50">
                        {rounds.map((r, i) => (
                            <tr key={i} className="hover:bg-slate-800/30">
                                <td className="px-4 py-2 font-mono text-slate-500">{r.ts}</td>
                                <td className="px-4 py-2 text-slate-300">#{r.round}</td>
                                <td className="px-4 py-2">{r.pool.toLocaleString()}</td>
                                <td className="px-4 py-2 text-white font-bold">{r.drivers > 0 ? r.drivers : "-"}</td>
                                <td className="px-4 py-2">
                                    {r.drivers > 0 ? (
                                        <div className="flex gap-2">
                                            <span className="text-emerald-400">{r.fte} FTE</span>
                                            <span className="text-slate-600">|</span>
                                            <span className="text-amber-400">{r.pt} PT</span>
                                        </div>
                                    ) : (
                                        <span className="text-red-400 flex items-center gap-1">
                                            <TrendingDown className="w-3 h-3" /> {r.uncovered} Uncovered
                                        </span>
                                    )}
                                </td>
                                <td className="px-4 py-2 text-right font-mono">
                                    {r.quality ? `${r.quality}%` : "-"}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// NEW: Repair Actions Log
function RepairLog({ events }: { events: any[] }) {
    const repairs = events.filter(e => e.event_type === "repair_action").reverse();
    if (repairs.length === 0) return null;

    return (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden mt-4">
            <div className="px-4 py-3 border-b border-slate-700 flex items-center gap-2 bg-emerald-950/20">
                <Zap className="w-4 h-4 text-emerald-500" />
                <h3 className="text-sm font-semibold text-emerald-200">Auto-Repair Actions</h3>
            </div>
            <div className="max-h-[200px] overflow-y-auto p-0">
                <table className="w-full text-left text-xs">
                    <tbody className="divide-y divide-slate-700/50">
                        {repairs.map((r, i) => (
                            <tr key={i} className="hover:bg-slate-800/30">
                                <td className="px-4 py-2 font-mono text-slate-500 w-24">{r.ts.split('T')[1].slice(0, 8)}</td>
                                <td className="px-4 py-2 text-slate-300">{r.message}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export default function RunDetailClient({ runData: initialRunData }: RunDetailClientProps) {
    const [activeTab, setActiveTab] = useState("results");
    const scrollRef = useRef<HTMLDivElement>(null);

    // Live Event Stream
    const {
        connected,
        events,
        metrics: liveMetrics,
        currentPhase,
        currentStep
    } = useEventStream(initialRunData.id);

    // Auto-scroll logs
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [events]);

    // Derived Metrics (prefer live over static)
    const isLive = connected || (initialRunData.insights as any).status === "RUNNING";
    const status = isLive ? "Running" : "Completed"; // Simple status logic

    // Driver Counts
    const staticFte = initialRunData.roster.filter(r => r.driver_type === 'FTE').length;
    const staticPt = initialRunData.roster.filter(r => r.driver_type !== 'FTE').length;
    const driverCount = liveMetrics.drivers_total ?? initialRunData.roster.length;
    const fteCount = liveMetrics.drivers_fte ?? staticFte;
    const ptCount = liveMetrics.drivers_pt ?? staticPt;

    // Financial / Quality Metrics
    const violationCount = liveMetrics.u_sum ?? initialRunData.insights.violation_count;
    const corePtShare = liveMetrics.core_pt_share_hours ?? initialRunData.insights.core_share;
    const totalHours = initialRunData.insights.total_hours; // live total hours not always emitted, check metrics

    // Determine Pipeline Step
    // Map phase string to stepper index or status
    // Default steps: "Data In" -> "Profiling" -> "Block Gen" -> "Capacity" -> "Set Partition" -> "Finalizing"
    // We pass raw status/phase to Stepper, assume it handles mapping or we map here.
    // Simplifying: if live, use currentPhase, else "completed" logic.
    const pipelineStatus = isLive && currentPhase ? currentPhase : (violationCount === 0 ? "completed" : "completed_with_issues");

    const statusColor = isLive
        ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
        : violationCount === 0
            ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
            : "bg-amber-500/20 text-amber-400 border-amber-500/30";

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <a href="/" className="text-slate-500 hover:text-slate-300 transition-colors">
                        <ArrowLeft className="w-5 h-5" />
                    </a>
                    <div>
                        <div className="flex items-center gap-3">
                            <h1 className="text-xl font-bold text-white font-mono">run_{initialRunData.id.slice(0, 8)}</h1>
                            <span className={cn(
                                "px-2 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wide border flex items-center gap-1.5",
                                statusColor
                            )}>
                                {isLive && <RefreshCw className="w-3 h-3 animate-spin" />}
                                {isLive ? (getPhaseDisplayName(currentPhase) || "Running") : (violationCount === 0 ? "Optimal" : "Feasible")}
                            </span>
                        </div>
                        <div className="text-sm text-slate-500 mt-0.5 flex items-center gap-3">
                            <span>{driverCount} Drivers</span>
                            <span>{fteCount} FTE / {ptCount} PT</span>
                            {totalHours > 0 && <span>{totalHours.toFixed(0)}h Total</span>}
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setActiveTab("results")}
                        className="gap-2 bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white"
                    >
                        <LayoutGrid className="w-4 h-4" /> View Roster
                    </Button>
                    <Button
                        size="sm"
                        onClick={() => exportRunPackage({ roster: initialRunData.roster, insights: initialRunData.insights, id: initialRunData.id })}
                        className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white"
                        disabled={isLive && initialRunData.roster.length === 0}
                    >
                        <Download className="w-4 h-4" /> Export Pack
                    </Button>
                </div>
            </div>

            {/* Pipeline Stepper */}
            <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-6">
                <PipelineStepper steps={getDefaultPipelineSteps(pipelineStatus)} />
                {isLive && currentStep && (
                    <div className="mt-4 flex items-center justify-between text-xs text-slate-400 bg-slate-900/50 p-2 rounded border border-slate-800">
                        <span className="font-mono text-emerald-400">{currentStep}</span>
                        {liveMetrics.total_runtime_s !== undefined && (
                            <span>Elapsed: {formatElapsed(liveMetrics.total_runtime_s)}</span>
                        )}
                    </div>
                )}
            </div>

            {/* KPI Grid */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <KPICard
                    label="Core PT Share"
                    value={`${corePtShare.toFixed(1)}%`}
                    sublabel={corePtShare < 20 ? "Target: < 20% ✓" : "Above target"}
                    variant={corePtShare < 20 ? "success" : "warning"}
                />
                <KPICard
                    label="Drivers Active"
                    value={driverCount}
                    sublabel={`${fteCount} FTE · ${ptCount} PT`}
                />
                <KPICard
                    label="Feasibility"
                    value={violationCount === 0 ? "u_sum: 0" : `${violationCount} issues`}
                    sublabel={violationCount === 0 ? "All constraints met" : "Review required"}
                    variant={violationCount === 0 ? "success" : "danger"}
                />
                <KPICard
                    label="Pool Utilization"
                    value={liveMetrics.pool_total ? `${liveMetrics.pool_total}` : (initialRunData.roster.length > 0 ? "100%" : "-")}
                    sublabel={liveMetrics.pool_total ? "Columns in RMP" : "N/A"}
                />
            </div>

            {/* Tabs */}
            <Tabs defaultValue="results" value={activeTab} onValueChange={setActiveTab} className="w-full">
                <div className="border-b border-slate-700">
                    <TabsList className="bg-transparent h-auto p-0 gap-0">
                        {[
                            { id: 'results', label: 'Roster Matrix', icon: LayoutGrid },
                            { id: 'logs', label: 'Live Events', icon: Activity },
                        ].map((tab) => (
                            <TabsTrigger
                                key={tab.id}
                                value={tab.id}
                                className="px-5 py-3 rounded-none border-b-2 border-transparent data-[state=active]:border-emerald-500 data-[state=active]:text-emerald-400 data-[state=active]:shadow-none flex items-center gap-2 text-slate-400 hover:text-slate-200"
                            >
                                <tab.icon className="w-4 h-4" />
                                {tab.label}
                            </TabsTrigger>
                        ))}
                    </TabsList>
                </div>

                <TabsContent value="results" className="mt-6 space-y-4">
                    {/* Insights Panel */}
                    <InsightsPanel insights={initialRunData.insights} violationCount={violationCount} />

                    {/* Export Buttons if data available */}
                    {initialRunData.roster.length > 0 ? (
                        <>
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-slate-400">{initialRunData.roster.length} Drivers</span>
                                <div className="flex items-center gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => exportRosterToCSV(initialRunData.roster, initialRunData.id)}
                                        className="gap-2 bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white text-xs"
                                    >
                                        <Download className="w-3 h-3" /> Roster CSV
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => exportInsightsToCSV(initialRunData.insights, initialRunData.id)}
                                        className="gap-2 bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white text-xs"
                                    >
                                        <Download className="w-3 h-3" /> Insights CSV
                                    </Button>
                                </div>
                            </div>
                            <RosterMatrix data={initialRunData.roster} />
                        </>
                    ) : (
                        <div className="flex flex-col items-center justify-center h-64 border border-slate-800 rounded-lg bg-slate-900/50">
                            {isLive ? (
                                <>
                                    <Activity className="w-8 h-8 text-blue-500 animate-pulse mb-3" />
                                    <p className="text-slate-300 font-medium">Optimization in Progress</p>
                                    <p className="text-slate-500 text-sm mt-1">Roster will be available upon completion.</p>
                                </>
                            ) : (
                                <p className="text-slate-500">No roster data available.</p>
                            )}
                        </div>
                    )}
                </TabsContent>

                <TabsContent value="logs" className="mt-6">
                    {/* Live Insights & Rounds */}
                    <RmpRoundsTable events={events} />
                    <RepairLog events={events} />

                    <div className="bg-slate-950 rounded-lg border border-slate-800 flex flex-col h-[500px] mt-4">
                        <div className="p-3 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
                            <div className="flex items-center gap-2">
                                <Activity className="w-4 h-4 text-emerald-400" />
                                <span className="text-sm font-medium text-slate-200">Event Stream</span>
                                <span className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-500"}`} title={connected ? "Connected" : "Disconnected"} />
                            </div>
                            <span className="text-xs text-slate-500 font-mono">
                                {events.length} events
                            </span>
                        </div>
                        <div
                            ref={scrollRef}
                            className="flex-1 overflow-y-auto p-4 space-y-2 font-mono text-xs"
                        >
                            {events.length === 0 && (
                                <div className="text-slate-600 text-center italic mt-10">Waiting for events...</div>
                            )}
                            {events.map((evt, i) => (
                                <div key={i} className="flex gap-2">
                                    <span className="text-slate-500 shrink-0 select-none">
                                        [{evt.ts.split('T')[1].slice(0, 12)}]
                                    </span>
                                    <span className={cn(
                                        "shrink-0 font-bold w-24 truncate",
                                        evt.level === "ERROR" ? "text-red-400" :
                                            evt.level === "WARN" ? "text-amber-400" :
                                                evt.event_type === "phase_start" ? "text-blue-400" :
                                                    evt.event_type === "phase_end" ? "text-blue-400" :
                                                        evt.event_type === "improvement" ? "text-emerald-400" :
                                                            "text-slate-400"
                                    )}>
                                        {evt.event_type}
                                    </span>
                                    <span className={cn(
                                        "break-all",
                                        evt.level === "ERROR" ? "text-red-300" : "text-slate-300"
                                    )}>
                                        {evt.message}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </TabsContent>
            </Tabs>
        </div>
    );
}
