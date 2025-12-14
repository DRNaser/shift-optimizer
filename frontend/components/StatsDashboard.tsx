// Stats Dashboard Component
// Shows KPIs and optimization statistics

import React from 'react';
import { StatsOutput, ValidationOutput } from '../types';

interface StatsDashboardProps {
    stats: StatsOutput;
    validation: ValidationOutput;
    solverType: string;
}

export default function StatsDashboard({ stats, validation, solverType }: StatsDashboardProps) {
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {/* Assignment Rate */}
            <StatCard
                label="Assignment Rate"
                value={`${(stats.assignment_rate * 100).toFixed(0)}%`}
                icon="🎯"
                color={stats.assignment_rate >= 0.9 ? 'green' : stats.assignment_rate >= 0.7 ? 'yellow' : 'red'}
            />

            {/* Tours Assigned */}
            <StatCard
                label="Tours Assigned"
                value={`${stats.total_tours_assigned}/${stats.total_tours_input}`}
                icon="📦"
                color="blue"
            />

            {/* Drivers Used */}
            <StatCard
                label="Drivers Used"
                value={stats.total_drivers.toString()}
                icon="👤"
                color="purple"
            />

            {/* Utilization */}
            <StatCard
                label="Avg Utilization"
                value={`${(stats.average_driver_utilization * 100).toFixed(0)}%`}
                icon="⚡"
                color={stats.average_driver_utilization >= 0.6 ? 'green' : 'yellow'}
            />

            {/* Block Counts */}
            <div className="col-span-2 md:col-span-4 bg-white rounded-xl shadow p-4">
                <div className="flex items-center gap-6 justify-center">
                    <BlockStat type="3er" count={stats.block_counts['triple'] || 0} color="#22c55e" />
                    <BlockStat type="2er" count={stats.block_counts['double'] || 0} color="#3b82f6" />
                    <BlockStat type="1er" count={stats.block_counts['single'] || 0} color="#f59e0b" />

                    <div className="border-l border-gray-200 pl-6 ml-2">
                        <span className="text-xs text-gray-500 uppercase tracking-wider">Solver</span>
                        <div className="font-semibold text-gray-800">{solverType.toUpperCase()}</div>
                    </div>

                    {validation.is_valid ? (
                        <div className="flex items-center gap-2 text-green-600">
                            <span className="text-xl">✓</span>
                            <span className="font-medium">Valid</span>
                        </div>
                    ) : (
                        <div className="flex items-center gap-2 text-red-600">
                            <span className="text-xl">✗</span>
                            <span className="font-medium">{validation.hard_violations.length} violations</span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// Individual stat card
interface StatCardProps {
    label: string;
    value: string;
    icon: string;
    color: 'green' | 'yellow' | 'red' | 'blue' | 'purple';
}

function StatCard({ label, value, icon, color }: StatCardProps) {
    const bgColors = {
        green: 'bg-green-50 border-green-200',
        yellow: 'bg-yellow-50 border-yellow-200',
        red: 'bg-red-50 border-red-200',
        blue: 'bg-blue-50 border-blue-200',
        purple: 'bg-purple-50 border-purple-200',
    };

    const textColors = {
        green: 'text-green-600',
        yellow: 'text-yellow-600',
        red: 'text-red-600',
        blue: 'text-blue-600',
        purple: 'text-purple-600',
    };

    return (
        <div className={`rounded-xl border p-4 ${bgColors[color]}`}>
            <div className="flex items-center gap-3">
                <span className="text-2xl">{icon}</span>
                <div>
                    <div className={`text-2xl font-bold ${textColors[color]}`}>
                        {value}
                    </div>
                    <div className="text-sm text-gray-600">{label}</div>
                </div>
            </div>
        </div>
    );
}

// Block type stat
interface BlockStatProps {
    type: string;
    count: number;
    color: string;
}

function BlockStat({ type, count, color }: BlockStatProps) {
    return (
        <div className="flex items-center gap-2">
            <div
                className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-sm"
                style={{ backgroundColor: color }}
            >
                {count}
            </div>
            <span className="text-sm text-gray-600">{type}</span>
        </div>
    );
}
