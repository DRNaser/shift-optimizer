import type { AssignmentOutput, WeekdayFE } from '../api';

interface ScheduleGridProps {
    assignments: AssignmentOutput[];
}

const DAYS: WeekdayFE[] = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'];
const DAY_LABELS: Record<WeekdayFE, string> = {
    MONDAY: 'Mon',
    TUESDAY: 'Tue',
    WEDNESDAY: 'Wed',
    THURSDAY: 'Thu',
    FRIDAY: 'Fri',
    SATURDAY: 'Sat',
    SUNDAY: 'Sun',
};

export function ScheduleGrid({ assignments }: ScheduleGridProps) {
    // Group by driver and compute hours
    const driverMap = new Map<string, Map<WeekdayFE, AssignmentOutput[]>>();
    const driverHours = new Map<string, number>();
    const driverNames = new Map<string, string>();

    for (const a of assignments) {
        if (!driverMap.has(a.driver_id)) {
            driverMap.set(a.driver_id, new Map());
            driverNames.set(a.driver_id, a.driver_name);
        }
        const dayMap = driverMap.get(a.driver_id)!;
        if (!dayMap.has(a.day)) {
            dayMap.set(a.day, []);
        }
        dayMap.get(a.day)!.push(a);

        // Sum hours
        const current = driverHours.get(a.driver_id) || 0;
        driverHours.set(a.driver_id, current + a.block.total_work_hours);
    }

    const drivers = Array.from(driverMap.keys()).sort();

    if (drivers.length === 0) {
        return (
            <div className="card text-center">
                <p className="text-muted">No assignments to display</p>
            </div>
        );
    }

    return (
        <div className="schedule-grid">
            {/* Header row */}
            <div className="schedule-header-cell">Driver</div>
            {DAYS.map((day) => (
                <div key={day} className="schedule-header-cell">{DAY_LABELS[day]}</div>
            ))}

            {/* Driver rows */}
            {drivers.map((driverId) => {
                const totalHours = driverHours.get(driverId) || 0;
                const driverName = driverNames.get(driverId) || driverId;

                return (
                    <>
                        <div key={`${driverId}-label`} className="schedule-driver-cell" style={{ flexDirection: 'column', alignItems: 'flex-start', justifyContent: 'center', lineHeight: '1.2' }}>
                            <div style={{ fontWeight: 600 }}>{driverName}</div>
                            <div style={{ fontSize: '0.85em', color: 'var(--text-secondary)' }}>{totalHours.toFixed(1)} h</div>
                        </div>
                        {DAYS.map((day) => {
                            const dayAssignments = driverMap.get(driverId)?.get(day) || [];
                            return (
                                <div key={`${driverId}-${day}`} className="schedule-cell">
                                    {dayAssignments.map((a) => (
                                        <div
                                            key={a.block.id}
                                            className={`schedule-block ${a.block.block_type}`}
                                            title={`${a.block.tours.length} tours, ${a.block.total_work_hours.toFixed(1)}h`}
                                        >
                                            {a.block.tours.map((t) => t.start_time).join(', ')}
                                        </div>
                                    ))}
                                </div>
                            );
                        })}
                    </>
                );
            })}
        </div>
    );
}
