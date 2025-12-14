
import React from 'react';
import { Stats } from '../types';

interface StatsPanelProps {
  stats: Stats;
}

interface StatCardProps {
    label: string;
    value: number | string;
    color: string;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, color }) => (
    <div className={`p-4 rounded-lg shadow flex-1 ${color}`}>
        <p className="text-sm font-medium text-slate-600">{label}</p>
        <p className="text-3xl font-bold text-slate-800">{value}</p>
    </div>
)

const StatsPanel: React.FC<StatsPanelProps> = ({ stats }) => {
  return (
    <div>
        <h3 className="text-xl font-semibold text-slate-600 mb-4">Statistics</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 text-center">
            <StatCard label="Drivers Used" value={stats.total_drivers_used} color="bg-blue-100" />
            <StatCard label="Shifts Input" value={stats.total_shifts_input} color="bg-slate-100" />
            <StatCard label="Shifts Utilized" value={stats.total_shifts_output} color="bg-slate-100" />
            <StatCard label="3-Shift Blocks" value={stats["3er_count"]} color="bg-green-100" />
            <StatCard label="2-Shift Blocks" value={stats["2er_count"]} color="bg-sky-100" />
            <StatCard label="1-Shift Blocks" value={stats["1er_count"]} color="bg-yellow-100" />
        </div>
    </div>
  );
};

export default StatsPanel;
