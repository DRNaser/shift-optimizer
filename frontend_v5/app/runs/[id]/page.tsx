import Link from "next/link";
import { LayoutGrid, Activity, ScrollText, Package, Settings } from "lucide-react";
import RunDetailClient from "./run-detail-client";
import { RunDetailData } from "@/lib/types";
import { transformScheduleToRunDetail } from "@/lib/transform-run-data";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

async function fetchRunData(id: string): Promise<RunDetailData> {
    const res = await fetch(`${API_BASE}/runs/${id}/plan`, {
        cache: "no-store",
    });

    if (!res.ok) {
        throw new Error(`API returned ${res.status}: ${res.statusText}`);
    }

    const schedule = await res.json();
    return transformScheduleToRunDetail(schedule);
}

async function fetchRunStatus(id: string): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/runs/${id}/status`, {
        cache: "no-store",
    });

    if (!res.ok) {
        throw new Error(`Status fetch failed: ${res.statusText}`);
    }

    return res.json();
}

// Sidebar Navigation Component
function Sidebar({ currentPage }: { currentPage: string }) {
    const navItems = [
        { id: "overview", icon: LayoutGrid, label: "Runs Overview", href: "/" },
        { id: "detail", icon: Activity, label: "Run Detail", href: "#" },
        { id: "matrix", icon: LayoutGrid, label: "Roster Matrix", href: "#" },
        { id: "logs", icon: ScrollText, label: "System Logs", href: "#" },
        { id: "artifacts", icon: Package, label: "Artifacts", href: "#" },
    ];

    return (
        <aside className="w-56 bg-slate-800/50 border-r border-slate-700/50 flex flex-col shrink-0">
            <div className="p-5 border-b border-slate-700/50">
                <Link href="/" className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center">
                        <span className="text-white font-bold text-sm">S</span>
                    </div>
                    <div>
                        <h1 className="text-base font-bold text-white">SOLVEREIGN</h1>
                        <p className="text-[10px] text-slate-500 font-mono">v7.0.0-freeze</p>
                    </div>
                </Link>
            </div>

            <nav className="flex-1 p-3 space-y-1">
                {navItems.map((item) => (
                    <Link
                        key={item.id}
                        href={item.href}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${currentPage === item.id
                            ? "bg-emerald-600/20 text-emerald-400"
                            : "text-slate-400 hover:bg-slate-700/50 hover:text-slate-200"
                            }`}
                    >
                        <item.icon className="w-4 h-4" />
                        {item.label}
                    </Link>
                ))}
            </nav>

            <div className="p-3 border-t border-slate-700/50">
                <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-500">
                    <Settings className="w-4 h-4" />
                    Config (Read-Only)
                </div>
            </div>
        </aside>
    );
}

interface PageProps {
    params: Promise<{ id: string }>;
}

export default async function RunDetailPage({ params }: PageProps) {
    const { id } = await params;

    let runData: RunDetailData;
    let isLive = false;
    let statusError = "";

    try {
        runData = await fetchRunData(id);
    } catch (err) {
        // Plan fetch failed, check if running
        try {
            const statusFn = await fetchRunStatus(id);
            if (statusFn.status === "RUNNING" || statusFn.status === "QUEUED") {
                isLive = true;
                // Create skeleton data for live view
                runData = {
                    id: id,
                    roster: [], // Empty roster for running state
                    insights: {
                        total_hours: 0,
                        core_share: 0,
                        orphans_count: 0,
                        violation_count: 0,
                        status: statusFn.status
                    }
                };
            } else {
                statusError = `Run is ${statusFn.status} but no plan available.`;
                throw err;
            }
        } catch (statusErr) {
            // Both failed
            const error = err instanceof Error ? err.message : "Unknown error";
            return (
                <div className="min-h-screen bg-slate-900 text-slate-100 flex">
                    <Sidebar currentPage="detail" />
                    <main className="flex-1 p-8">
                        <div className="max-w-4xl">
                            <div className="p-8 border border-red-500/30 rounded-lg bg-red-500/10">
                                <h1 className="text-xl font-semibold text-red-400 mb-2">Failed to Load Run</h1>
                                <p className="text-red-300 mb-4">
                                    Run ID: <code className="bg-red-500/20 px-1 rounded">{id}</code>
                                </p>
                                <p className="text-sm text-red-400/80 mb-4">{error}</p>
                                {statusError && <p className="text-sm text-yellow-400/80 mb-4">{statusError}</p>}
                                <div className="p-4 bg-slate-800 rounded border border-slate-700">
                                    <p className="text-sm text-slate-400 mb-2">
                                        backend: {API_BASE}
                                    </p>
                                </div>
                            </div>
                        </div>
                    </main>
                </div>
            );
        }
    }

    return (
        <div className="min-h-screen bg-slate-900 text-slate-100 flex">
            <Sidebar currentPage="detail" />
            <main className="flex-1 overflow-y-auto">
                <div className="p-6">
                    <RunDetailClient runData={runData} />
                </div>
            </main>
        </div>
    );
}
