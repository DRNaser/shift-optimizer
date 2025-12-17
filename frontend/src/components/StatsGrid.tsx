import type { StatsOutput } from '../api';

interface StatsGridProps {
    stats: StatsOutput;
}

export function StatsGrid({ stats }: StatsGridProps) {
    const assignmentRate = (stats.assignment_rate * 100).toFixed(1);
    const utilization = (stats.average_driver_utilization * 100).toFixed(1);

    return (
        <div className="stats-grid">
            <div className="stat-card">
                <div className="stat-value">{stats.total_drivers}</div>
                <div className="stat-label">Drivers Used</div>
            </div>
            <div className="stat-card">
                <div className="stat-value">{stats.total_tours_assigned}</div>
                <div className="stat-label">Tours Assigned</div>
            </div>
            <div className="stat-card">
                <div className="stat-value" style={{ color: stats.total_tours_unassigned > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
                    {stats.total_tours_unassigned}
                </div>
                <div className="stat-label">Unassigned</div>
            </div>
            <div className="stat-card">
                <div className="stat-value">{assignmentRate}%</div>
                <div className="stat-label">Assignment Rate</div>
            </div>
            <div className="stat-card">
                <div className="stat-value">{utilization}%</div>
                <div className="stat-label">Avg Utilization</div>
            </div>
            <div className="stat-card">
                <div className="stat-value">{stats.average_work_hours.toFixed(1)}h</div>
                <div className="stat-label">Avg Hours</div>
            </div>
            <div className="stat-card">
                <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
                    <span className="badge badge-info">{stats.block_counts.single} 1er</span>
                    <span className="badge badge-success">{stats.block_counts.double} 2er</span>
                    <span className="badge badge-warning">{stats.block_counts.triple} 3er</span>
                </div>
                <div className="stat-label mt-sm">Block Distribution</div>
            </div>
        </div >
    );
}
