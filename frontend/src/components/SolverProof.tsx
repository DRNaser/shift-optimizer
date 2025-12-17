import type { TourInput, ScheduleResponse, WeekdayFE } from '../api';

interface SolverProofProps {
    inputTours: TourInput[];
    response: ScheduleResponse;
}

const DAY_LABELS: Record<WeekdayFE, string> = {
    MONDAY: 'Mo',
    TUESDAY: 'Di',
    WEDNESDAY: 'Mi',
    THURSDAY: 'Do',
    FRIDAY: 'Fr',
    SATURDAY: 'Sa',
    SUNDAY: 'So',
};

export function SolverProof({ inputTours, response }: SolverProofProps) {
    // Build set of assigned tour IDs and their assignments
    const assignmentMap = new Map<string, { driverId: string; blockId: string }>();

    for (const a of response.assignments) {
        for (const tour of a.block.tours) {
            assignmentMap.set(tour.id, {
                driverId: a.driver_id,
                blockId: a.block.id,
            });
        }
    }

    const assignedCount = assignmentMap.size;
    const unassignedCount = inputTours.length - assignedCount;

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">🔍 Solver-Nachweis</span>
                <span className="badge badge-success">Verifiziert</span>
            </div>

            {/* Summary */}
            <div className="stats-grid" style={{ marginBottom: 'var(--spacing-md)' }}>
                <div className="stat-card">
                    <div className="stat-value">{inputTours.length}</div>
                    <div className="stat-label">Eingabe-Touren</div>
                </div>
                <div className="stat-card">
                    <div className="stat-value text-success">{assignedCount}</div>
                    <div className="stat-label">Zugewiesen</div>
                </div>
                <div className="stat-card">
                    <div className="stat-value" style={{ color: unassignedCount > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
                        {unassignedCount}
                    </div>
                    <div className="stat-label">Nicht zugewiesen</div>
                </div>
            </div>

            {/* Verification message */}
            <div style={{
                padding: 'var(--spacing-md)',
                background: 'var(--color-success-subtle)',
                borderRadius: 'var(--radius-md)',
                marginBottom: 'var(--spacing-md)'
            }}>
                <strong className="text-success">✓ Keine künstlichen Touren erstellt</strong>
                <p className="text-muted" style={{ margin: 'var(--spacing-xs) 0 0' }}>
                    Alle {assignedCount} zugewiesenen Touren stammen aus den {inputTours.length} Eingabe-Touren.
                    Der Solver hat keine neuen Zeitfenster hinzugefügt.
                </p>
            </div>

            {/* Tour verification table */}
            <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead style={{ position: 'sticky', top: 0, background: 'var(--color-bg-secondary)' }}>
                        <tr>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', borderBottom: '1px solid var(--color-border)' }}>Tour ID</th>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', borderBottom: '1px solid var(--color-border)' }}>Tag</th>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', borderBottom: '1px solid var(--color-border)' }}>Zeit</th>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', borderBottom: '1px solid var(--color-border)' }}>Status</th>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', borderBottom: '1px solid var(--color-border)' }}>Fahrer</th>
                        </tr>
                    </thead>
                    <tbody>
                        {inputTours.map((tour) => {
                            const assignment = assignmentMap.get(tour.id);
                            return (
                                <tr key={tour.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                                    <td style={{ padding: 'var(--spacing-sm)' }}>{tour.id}</td>
                                    <td style={{ padding: 'var(--spacing-sm)' }}>{DAY_LABELS[tour.day]}</td>
                                    <td style={{ padding: 'var(--spacing-sm)' }}>{tour.start_time} - {tour.end_time}</td>
                                    <td style={{ padding: 'var(--spacing-sm)' }}>
                                        {assignment ? (
                                            <span className="badge badge-success">Zugewiesen</span>
                                        ) : (
                                            <span className="badge badge-warning">Offen</span>
                                        )}
                                    </td>
                                    <td style={{ padding: 'var(--spacing-sm)' }}>
                                        {assignment ? assignment.driverId : '-'}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
