import { useEffect, useState } from 'react';
import { fetchConstraints } from '../api';

// The API returns hard_constraints with UPPERCASE keys
interface ActualConstraintsResponse {
    hard_constraints?: {
        MAX_WEEKLY_HOURS?: number;
        MAX_DAILY_SPAN_HOURS?: number;
        MIN_REST_HOURS?: number;
        MAX_TOURS_PER_DAY?: number;
    };
}

export function HealthWidget() {
    const [constraints, setConstraints] = useState<ActualConstraintsResponse | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        fetchConstraints()
            .then((data) => setConstraints(data as unknown as ActualConstraintsResponse))
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

    // Defensive access - handle both old and new API formats
    const hard = constraints.hard_constraints || {};
    const maxHours = hard.MAX_WEEKLY_HOURS ?? 55;
    const minHours = 42; // Default min hours
    const maxSpan = hard.MAX_DAILY_SPAN_HOURS ?? 15.5;
    const minRest = hard.MIN_REST_HOURS ?? 11;

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">⚙️ Solver Constraints</span>
                <span className="badge badge-success">Active</span>
            </div>
            <div style={{ display: 'grid', gap: 'var(--spacing-sm)' }}>
                <div className="flex justify-between">
                    <span className="text-muted">FTE Hours</span>
                    <strong>{minHours}–{maxHours}h</strong>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted">Max Daily Span</span>
                    <strong>{maxSpan}h</strong>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted">Min Rest</span>
                    <strong>{minRest}h</strong>
                </div>
            </div>
        </div>
    );
}
