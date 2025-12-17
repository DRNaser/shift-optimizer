import { useEffect, useState } from 'react';
import { fetchConstraints, type ConstraintsResponse } from '../api';

export function HealthWidget() {
    const [constraints, setConstraints] = useState<ConstraintsResponse | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        fetchConstraints()
            .then(setConstraints)
            .catch((e) => setError(e.message));
    }, []);

    if (error) {
        return (
            <div className="card">
                <div className="card-header">
                    <span className="card-title">⚠️ Connection Error</span>
                </div>
                <p className="text-muted">{error}</p>
            </div>
        );
    }

    if (!constraints) {
        return (
            <div className="card">
                <div className="card-header">
                    <span className="card-title">Constraints</span>
                </div>
                <div className="flex items-center gap-sm">
                    <div className="spinner"></div>
                    <span className="text-muted">Loading...</span>
                </div>
            </div>
        );
    }

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">⚙️ Solver Constraints</span>
                <span className="badge badge-success">Active</span>
            </div>
            <div style={{ display: 'grid', gap: 'var(--spacing-sm)' }}>
                <div className="flex justify-between">
                    <span className="text-muted">FTE Hours</span>
                    <strong>{constraints.hard.min_hours_per_fte}–{constraints.hard.max_hours_per_fte}h</strong>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted">Max Daily Span</span>
                    <strong>{constraints.hard.max_daily_span_hours}h</strong>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted">Min Rest</span>
                    <strong>{constraints.hard.min_rest_hours}h</strong>
                </div>
                <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: 'var(--spacing-xs) 0' }} />
                <div className="flex justify-between">
                    <span className="text-muted">Target 2er Ratio</span>
                    <strong>{(constraints.soft.target_2er_ratio * 100).toFixed(0)}%</strong>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted">Target 3er Ratio</span>
                    <strong>{(constraints.soft.target_3er_ratio * 100).toFixed(0)}%</strong>
                </div>
            </div>
        </div>
    );
}
