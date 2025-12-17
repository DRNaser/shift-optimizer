import type { TourInput, ScheduleResponse, WeekdayFE } from '../api';

interface LeftoverToursProps {
    inputTours: TourInput[];
    response: ScheduleResponse;
}

const DAY_LABELS: Record<WeekdayFE, string> = {
    MONDAY: 'Montag',
    TUESDAY: 'Dienstag',
    WEDNESDAY: 'Mittwoch',
    THURSDAY: 'Donnerstag',
    FRIDAY: 'Freitag',
    SATURDAY: 'Samstag',
    SUNDAY: 'Sonntag',
};

export function LeftoverTours({ inputTours, response }: LeftoverToursProps) {
    // Build set of assigned tour IDs
    const assignedTourIds = new Set<string>();
    for (const a of response.assignments) {
        for (const tour of a.block.tours) {
            assignedTourIds.add(tour.id);
        }
    }

    const leftoverTours = inputTours.filter(t => !assignedTourIds.has(t.id));

    // Group by day for better overview
    const byDay = new Map<WeekdayFE, TourInput[]>();
    for (const tour of leftoverTours) {
        if (!byDay.has(tour.day)) {
            byDay.set(tour.day, []);
        }
        byDay.get(tour.day)!.push(tour);
    }

    if (leftoverTours.length === 0) {
        return (
            <div className="card">
                <div className="card-header">
                    <span className="card-title">✓ Keine Resttouren</span>
                </div>
                <div style={{
                    padding: 'var(--spacing-lg)',
                    textAlign: 'center',
                    background: 'var(--color-success-subtle)',
                    borderRadius: 'var(--radius-md)'
                }}>
                    <strong className="text-success">Alle Touren wurden erfolgreich zugewiesen!</strong>
                    <p className="text-muted" style={{ margin: 'var(--spacing-sm) 0 0' }}>
                        100% Abdeckung erreicht.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">⚠️ Resttouren ({leftoverTours.length})</span>
                <span className="badge badge-warning">{leftoverTours.length} nicht zugewiesen</span>
            </div>

            <div style={{
                padding: 'var(--spacing-md)',
                background: 'var(--color-warning-subtle)',
                borderRadius: 'var(--radius-md)',
                marginBottom: 'var(--spacing-md)'
            }}>
                <p className="text-muted" style={{ margin: 0 }}>
                    Diese Touren konnten nicht zugewiesen werden, da keine passenden Fahrer mit
                    verfügbarer Kapazität oder kompatiblen Zeitfenstern gefunden wurden.
                </p>
            </div>

            {/* Group by day */}
            {Array.from(byDay.entries())
                .sort(([a], [b]) => {
                    const order: WeekdayFE[] = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'];
                    return order.indexOf(a) - order.indexOf(b);
                })
                .map(([day, tours]) => (
                    <div key={day} style={{ marginBottom: 'var(--spacing-md)' }}>
                        <h4 style={{
                            fontSize: '0.875rem',
                            fontWeight: 600,
                            marginBottom: 'var(--spacing-sm)',
                            color: 'var(--color-text-secondary)'
                        }}>
                            {DAY_LABELS[day]} ({tours.length} Touren)
                        </h4>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--spacing-sm)' }}>
                            {tours.map((tour) => (
                                <div
                                    key={tour.id}
                                    style={{
                                        padding: 'var(--spacing-sm) var(--spacing-md)',
                                        background: 'var(--color-bg-tertiary)',
                                        borderRadius: 'var(--radius-md)',
                                        border: '1px solid var(--color-border)',
                                        fontSize: '0.8rem',
                                    }}
                                >
                                    <strong>{tour.id}</strong>
                                    <span className="text-muted" style={{ marginLeft: 'var(--spacing-sm)' }}>
                                        {tour.start_time} - {tour.end_time}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
        </div>
    );
}
