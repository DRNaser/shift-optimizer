'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import {
    getRunReport,
    getRunReportCanonical,
    getRunPlan,
    downloadJson,
    downloadText,
    type RunReport,
    type PlanResponse,
    type AssignmentOutput
} from '@/utils/api';
import { exportRosterXlsx } from '@/utils/rosterExport';
import { buildResultBullets, type Bullet } from '@/utils/resultBullets';

type DriverType = 'ALL' | 'FTE' | 'PT';
type BlockType = 'ALL' | 'SINGLE' | 'DOUBLE' | 'TRIPLE';

export default function ResultsPage() {
    const params = useParams();
    const runId = params.id as string;

    const [report, setReport] = useState<RunReport | null>(null);
    const [canonicalJson, setCanonicalJson] = useState<string | null>(null);
    const [plan, setPlan] = useState<PlanResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Filters
    const [driverTypeFilter, setDriverTypeFilter] = useState<DriverType>('ALL');
    const [blockTypeFilter, setBlockTypeFilter] = useState<BlockType>('ALL');
    const [dayFilter, setDayFilter] = useState<string>('ALL');
    const [showUnderfull, setShowUnderfull] = useState(false);

    // Active tab
    const [activeTab, setActiveTab] = useState<'overview' | 'assignments' | 'config'>('overview');

    // Load data
    useEffect(() => {
        async function loadData() {
            try {
                const [reportData, planData, canonical] = await Promise.all([
                    getRunReport(runId),
                    getRunPlan(runId),
                    getRunReportCanonical(runId)
                ]);
                setReport(reportData);
                setPlan(planData);
                setCanonicalJson(canonical);
            } catch (e: any) {
                setError(e.message || 'Failed to load results');
            } finally {
                setLoading(false);
            }
        }
        loadData();
    }, [runId]);

    // Compute driver hours
    const driverHours: Record<string, number> = {};
    plan?.assignments.forEach(a => {
        driverHours[a.driver_id] = (driverHours[a.driver_id] || 0) + a.block.total_work_hours;
    });

    // Classify driver type (FTE if >= 42h, else PT)
    const driverTypes: Record<string, 'FTE' | 'PT'> = {};
    Object.entries(driverHours).forEach(([id, hours]) => {
        driverTypes[id] = hours >= 42 ? 'FTE' : 'PT';
    });

    // Filter assignments
    const filteredAssignments = (plan?.assignments || []).filter(a => {
        // Driver type filter
        if (driverTypeFilter !== 'ALL' && driverTypes[a.driver_id] !== driverTypeFilter) {
            return false;
        }

        // Block type filter
        if (blockTypeFilter !== 'ALL' && a.block.block_type.toUpperCase() !== blockTypeFilter) {
            return false;
        }

        // Day filter
        if (dayFilter !== 'ALL' && a.day.toLowerCase() !== dayFilter.toLowerCase()) {
            return false;
        }

        // Underfull filter
        if (showUnderfull) {
            const hours = driverHours[a.driver_id] || 0;
            if (driverTypes[a.driver_id] === 'FTE' && hours >= 42) {
                return false;
            }
        }

        return true;
    });

    // Get unique days
    const days = Array.from(new Set(plan?.assignments.map(a => a.day) || []));

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-[400px]">
                <div className="text-muted-foreground">Loading results...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="max-w-4xl mx-auto">
                <div className="p-6 bg-destructive/10 text-destructive rounded-lg">{error}</div>
                <a href="/" className="btn-secondary mt-4 inline-block">Back to Setup</a>
            </div>
        );
    }

    return (
        <div className="max-w-7xl mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">Results: {runId}</h1>
                    <p className="text-muted-foreground mt-1">
                        Solution Signature: <code className="text-xs bg-muted px-2 py-0.5 rounded">
                            {report?.solution_signature || 'N/A'}
                        </code>
                    </p>
                </div>

                <div className="flex gap-2">
                    <button
                        onClick={() => {
                            if (plan && report) {
                                const bullets = buildResultBullets(report, plan);
                                exportRosterXlsx({
                                    plan,
                                    report,
                                    bullets,
                                    filename: `roster_${runId}.xlsx`
                                });
                            }
                        }}
                        disabled={!plan || !report}
                        className="btn-primary btn-sm"
                    >
                        Download Roster XLSX
                    </button>
                    <button
                        onClick={() => report && downloadJson(report, `report_${runId}.json`)}
                        className="btn-secondary btn-sm"
                    >
                        Download Report
                    </button>
                    <button
                        onClick={() => canonicalJson && downloadText(canonicalJson, `canonical_${runId}.json`)}
                        className="btn-secondary btn-sm"
                    >
                        Download Canonical
                    </button>
                    <button
                        onClick={() => plan && downloadJson(plan, `plan_${runId}.json`)}
                        className="btn-secondary btn-sm"
                    >
                        Download Plan
                    </button>
                </div>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 mb-6 border-b">
                {(['overview', 'assignments', 'config'] as const).map(tab => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${activeTab === tab
                            ? 'border-primary text-primary'
                            : 'border-transparent text-muted-foreground hover:text-foreground'
                            }`}
                    >
                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                    </button>
                ))}
            </div>

            {/* Overview Tab */}
            {activeTab === 'overview' && (
                <div className="space-y-6">
                    {/* Stats Cards */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="card">
                            <div className="text-sm text-muted-foreground">Total Drivers</div>
                            <div className="text-3xl font-bold">{plan?.stats.total_drivers || 0}</div>
                        </div>
                        <div className="card">
                            <div className="text-sm text-muted-foreground">Tours Assigned</div>
                            <div className="text-3xl font-bold">
                                {plan?.stats.total_tours_assigned || 0}
                                <span className="text-lg text-muted-foreground">
                                    /{plan?.stats.total_tours_input || 0}
                                </span>
                            </div>
                        </div>
                        <div className="card">
                            <div className="text-sm text-muted-foreground">Assignment Rate</div>
                            <div className="text-3xl font-bold">
                                {((plan?.stats.assignment_rate || 0) * 100).toFixed(1)}%
                            </div>
                        </div>
                        <div className="card">
                            <div className="text-sm text-muted-foreground">Avg Hours/Driver</div>
                            <div className="text-3xl font-bold">
                                {(plan?.stats.average_work_hours || 0).toFixed(1)}h
                            </div>
                        </div>
                    </div>

                    {/* Result Bullets (KPI Traffic Lights) */}
                    {report && plan && (() => {
                        const bullets = buildResultBullets(report, plan);
                        if (bullets.length === 0) return null;

                        const Badge = ({ status }: { status: "GOOD" | "WARN" | "BAD" }) => {
                            const cls =
                                status === "GOOD" ? "bg-green-500/15 text-green-400 border-green-500/30" :
                                    status === "WARN" ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" :
                                        "bg-red-500/15 text-red-400 border-red-500/30";
                            return <span className={`rounded border px-2 py-0.5 text-xs ${cls}`}>{status}</span>;
                        };

                        return (
                            <div className="card">
                                <h3 className="text-lg font-semibold mb-4">Result Check</h3>
                                <ul className="space-y-2">
                                    {bullets.map((x, i) => (
                                        <li key={i} className="flex items-center justify-between rounded border border-border/50 p-2">
                                            <div className="flex items-center gap-2">
                                                <Badge status={x.status} />
                                                <span className="font-medium">{x.label}</span>
                                            </div>
                                            <div className="text-sm text-muted-foreground">{x.value ?? ""}</div>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        );
                    })()}

                    {/* Block Counts */}
                    <div className="card">
                        <h3 className="text-lg font-semibold mb-4">Block Distribution</h3>
                        <div className="grid grid-cols-3 gap-4">
                            {Object.entries(plan?.stats.block_counts || {}).map(([type, count]) => (
                                <div key={type} className="text-center p-4 bg-muted rounded-lg">
                                    <div className="text-2xl font-bold">{count}</div>
                                    <div className="text-sm text-muted-foreground">{type}</div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Timing */}
                    <div className="card">
                        <h3 className="text-lg font-semibold mb-4">Timing</h3>
                        <div className="grid grid-cols-4 gap-4">
                            <div>
                                <div className="text-sm text-muted-foreground">Phase 1</div>
                                <div className="text-xl font-mono">{report?.timing.phase1_s.toFixed(2)}s</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted-foreground">Phase 2</div>
                                <div className="text-xl font-mono">{report?.timing.phase2_s.toFixed(2)}s</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted-foreground">LNS</div>
                                <div className="text-xl font-mono">{report?.timing.lns_s.toFixed(2)}s</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted-foreground">Total</div>
                                <div className="text-xl font-mono font-bold">{report?.timing.total_s.toFixed(2)}s</div>
                            </div>
                        </div>
                    </div>

                    {/* Reason Codes */}
                    {(report?.reason_codes?.length || 0) > 0 && (
                        <div className="card">
                            <h3 className="text-lg font-semibold mb-4">Reason Codes</h3>
                            <div className="flex flex-wrap gap-2">
                                {report?.reason_codes.map((code, i) => (
                                    <span
                                        key={i}
                                        className={`px-3 py-1 rounded-full text-sm ${code.includes('OVERRUN') ? 'bg-destructive/10 text-destructive' :
                                            code.includes('WARN') ? 'bg-amber-100 text-amber-800' :
                                                'bg-muted text-muted-foreground'
                                            }`}
                                    >
                                        {code}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Validation */}
                    <div className="card">
                        <h3 className="text-lg font-semibold mb-4">Validation</h3>
                        <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full ${plan?.validation.is_valid ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                            }`}>
                            <span className={`w-2 h-2 rounded-full ${plan?.validation.is_valid ? 'bg-green-500' : 'bg-red-500'
                                }`} />
                            {plan?.validation.is_valid ? 'Valid' : 'Invalid'}
                        </div>

                        {(plan?.validation.hard_violations?.length || 0) > 0 && (
                            <div className="mt-4">
                                <div className="text-sm font-medium text-destructive mb-2">Hard Violations</div>
                                <ul className="list-disc list-inside text-sm text-destructive">
                                    {plan?.validation.hard_violations.map((v, i) => (
                                        <li key={i}>{v}</li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Assignments Tab */}
            {activeTab === 'assignments' && (
                <div>
                    {/* Filters */}
                    <div className="flex flex-wrap gap-4 mb-4">
                        <select
                            value={driverTypeFilter}
                            onChange={(e) => setDriverTypeFilter(e.target.value as DriverType)}
                            className="input h-9 w-32"
                        >
                            <option value="ALL">All Drivers</option>
                            <option value="FTE">FTE Only</option>
                            <option value="PT">PT Only</option>
                        </select>

                        <select
                            value={blockTypeFilter}
                            onChange={(e) => setBlockTypeFilter(e.target.value as BlockType)}
                            className="input h-9 w-32"
                        >
                            <option value="ALL">All Blocks</option>
                            <option value="SINGLE">1er</option>
                            <option value="DOUBLE">2er</option>
                            <option value="TRIPLE">3er</option>
                        </select>

                        <select
                            value={dayFilter}
                            onChange={(e) => setDayFilter(e.target.value)}
                            className="input h-9 w-32"
                        >
                            <option value="ALL">All Days</option>
                            {days.map(day => (
                                <option key={day} value={day}>{day}</option>
                            ))}
                        </select>

                        <label className="flex items-center gap-2 text-sm">
                            <input
                                type="checkbox"
                                checked={showUnderfull}
                                onChange={(e) => setShowUnderfull(e.target.checked)}
                            />
                            Underfull FTE only
                        </label>

                        <span className="text-sm text-muted-foreground ml-auto">
                            {filteredAssignments.length} assignments
                        </span>
                    </div>

                    {/* Table */}
                    <div className="card p-0 overflow-hidden">
                        <table className="table">
                            <thead>
                                <tr>
                                    <th>Driver</th>
                                    <th>Type</th>
                                    <th>Day</th>
                                    <th>Block</th>
                                    <th>Block Type</th>
                                    <th>Tours</th>
                                    <th>Hours</th>
                                    <th>Driver Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredAssignments.map((a, i) => (
                                    <tr key={i}>
                                        <td className="font-mono text-sm">{a.driver_id}</td>
                                        <td>
                                            <span className={`text-xs px-2 py-0.5 rounded ${driverTypes[a.driver_id] === 'FTE'
                                                ? 'bg-blue-100 text-blue-800'
                                                : 'bg-purple-100 text-purple-800'
                                                }`}>
                                                {driverTypes[a.driver_id]}
                                            </span>
                                        </td>
                                        <td>{a.day}</td>
                                        <td className="font-mono text-sm">{a.block.id}</td>
                                        <td>{a.block.block_type}</td>
                                        <td>{a.block.tours.length}</td>
                                        <td>{a.block.total_work_hours.toFixed(1)}h</td>
                                        <td className={`font-mono ${driverTypes[a.driver_id] === 'FTE' && (driverHours[a.driver_id] || 0) < 42
                                            ? 'text-amber-600'
                                            : ''
                                            }`}>
                                            {(driverHours[a.driver_id] || 0).toFixed(1)}h
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Config Tab */}
            {activeTab === 'config' && report?.config && (
                <div className="space-y-6">
                    <div className="card">
                        <h3 className="text-lg font-semibold mb-4">Effective Config</h3>
                        <div className="text-sm mb-4">
                            <span className="text-muted-foreground">Hash: </span>
                            <code className="bg-muted px-2 py-0.5 rounded">{report.config.effective_hash}</code>
                        </div>
                    </div>

                    <div className="card">
                        <h3 className="text-lg font-semibold mb-4 text-green-600">Applied Overrides</h3>
                        {Object.keys(report.config.overrides_applied).length === 0 ? (
                            <p className="text-muted-foreground text-sm">No overrides applied</p>
                        ) : (
                            <table className="table">
                                <thead>
                                    <tr>
                                        <th>Key</th>
                                        <th>Value</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(report.config.overrides_applied).map(([key, value]) => (
                                        <tr key={key}>
                                            <td className="font-mono">{key}</td>
                                            <td>{JSON.stringify(value)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>

                    <div className="card">
                        <h3 className="text-lg font-semibold mb-4 text-red-600">Rejected Overrides</h3>
                        {Object.keys(report.config.overrides_rejected).length === 0 ? (
                            <p className="text-muted-foreground text-sm">No overrides rejected</p>
                        ) : (
                            <table className="table">
                                <thead>
                                    <tr>
                                        <th>Key</th>
                                        <th>Reason</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(report.config.overrides_rejected).map(([key, reason]) => (
                                        <tr key={key}>
                                            <td className="font-mono">{key}</td>
                                            <td className="text-destructive">{reason}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>

                    <div className="card">
                        <h3 className="text-lg font-semibold mb-4 text-amber-600">Clamped Values</h3>
                        {Object.keys(report.config.overrides_clamped).length === 0 ? (
                            <p className="text-muted-foreground text-sm">No values clamped</p>
                        ) : (
                            <table className="table">
                                <thead>
                                    <tr>
                                        <th>Key</th>
                                        <th>Original</th>
                                        <th>Clamped To</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(report.config.overrides_clamped).map(([key, [original, clamped]]) => (
                                        <tr key={key}>
                                            <td className="font-mono">{key}</td>
                                            <td>{JSON.stringify(original)}</td>
                                            <td>{JSON.stringify(clamped)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
