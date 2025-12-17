import type { UnassignedTour } from '../api';

interface UnassignedListProps {
    tours: UnassignedTour[];
}

export function UnassignedList({ tours }: UnassignedListProps) {
    if (tours.length === 0) {
        return (
            <div className="card">
                <div className="card-header">
                    <span className="card-title">✓ All Tours Assigned</span>
                </div>
                <p className="text-success">No unassigned tours. Full coverage achieved!</p>
            </div>
        );
    }

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">⚠️ Unassigned Tours ({tours.length})</span>
            </div>
            <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', color: 'var(--color-text-muted)' }}>Tour</th>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', color: 'var(--color-text-muted)' }}>Day</th>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', color: 'var(--color-text-muted)' }}>Time</th>
                            <th style={{ textAlign: 'left', padding: 'var(--spacing-sm)', color: 'var(--color-text-muted)' }}>Reason</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tours.map((item, i) => (
                            <tr key={i} style={{ borderBottom: '1px solid var(--color-border)' }}>
                                <td style={{ padding: 'var(--spacing-sm)' }}>{item.tour.id}</td>
                                <td style={{ padding: 'var(--spacing-sm)' }}>{item.tour.day}</td>
                                <td style={{ padding: 'var(--spacing-sm)' }}>{item.tour.start_time} - {item.tour.end_time}</td>
                                <td style={{ padding: 'var(--spacing-sm)' }}>
                                    <span className="badge badge-error">{item.reason}</span>
                                    {item.details && <span className="text-muted" style={{ marginLeft: '8px' }}>{item.details}</span>}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
