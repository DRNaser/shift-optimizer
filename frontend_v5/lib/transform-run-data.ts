import { RunDetailData, RosterRow, Shift, ShiftType, DriverType, RunInsights } from "./types";

interface AssignmentOutput {
    driver_id: string;
    driver_name: string;
    day: string;
    block: {
        id: string;
        day: string;
        block_type: string;
        tours: { start_time: string; end_time: string }[];
        total_work_hours: number;
    };
}

interface StatsOutput {
    total_drivers: number;
    total_tours_input: number;
    total_tours_assigned: number;
    total_tours_unassigned: number;
    block_counts: Record<string, number>;
    assignment_rate: number;
    average_driver_utilization: number;
    average_work_hours: number;
    drivers_fte: number;
    drivers_pt: number;
    total_hours?: number;
}

interface ScheduleResponse {
    id: string;
    week_start: string;
    assignments: AssignmentOutput[];
    stats: StatsOutput;
    validation: {
        is_valid: boolean;
        hard_violations: string[];
    };
}

const DAY_INDEX: Record<string, number> = {
    'MONDAY': 0, 'Mon': 0, 'Monday': 0,
    'TUESDAY': 1, 'Tue': 1, 'Tuesday': 1,
    'WEDNESDAY': 2, 'Wed': 2, 'Wednesday': 2,
    'THURSDAY': 3, 'Thu': 3, 'Thursday': 3,
    'FRIDAY': 4, 'Fri': 4, 'Friday': 4,
    'SATURDAY': 5, 'Sat': 5, 'Saturday': 5,
};

function normalizeShiftType(blockType: string): ShiftType {
    const normalized = blockType.toLowerCase().replace(/[^a-z0-9_]/g, '');
    if (normalized.includes('3er') || normalized === '3er') return '3er';
    if (normalized.includes('2er_split') || normalized.includes('2ersplit')) return '2er_split';
    if (normalized.includes('2er') || normalized === '2er') return '2er';
    return '1er';
}

function getDriverType(weeklyHours: number): DriverType {
    if (weeklyHours >= 40) return 'FTE';
    if (weeklyHours >= 13.5) return 'PT_core';
    return 'PT_flex';
}

export function transformScheduleToRunDetail(schedule: ScheduleResponse): RunDetailData {
    // Group assignments by driver
    const driverMap = new Map<string, {
        name: string;
        totalHours: number;
        shifts: (Shift | null)[];
    }>();

    for (const assignment of schedule.assignments) {
        if (!driverMap.has(assignment.driver_id)) {
            driverMap.set(assignment.driver_id, {
                name: assignment.driver_name,
                totalHours: 0,
                shifts: [null, null, null, null, null, null], // Mon-Sat
            });
        }

        const driver = driverMap.get(assignment.driver_id)!;
        driver.totalHours += assignment.block.total_work_hours;

        const dayIdx = DAY_INDEX[assignment.day] ?? -1;
        if (dayIdx >= 0 && dayIdx <= 5) {
            const tours = assignment.block.tours || [];
            const startTime = tours[0]?.start_time || "00:00";
            const endTime = tours[tours.length - 1]?.end_time || "00:00";
            const shiftType = normalizeShiftType(assignment.block.block_type);

            driver.shifts[dayIdx] = {
                day_index: dayIdx,
                start_time: startTime,
                end_time: endTime,
                type: shiftType,
                is_split: shiftType === '2er_split',
            };
        }
    }

    // Convert to RosterRow array
    const roster: RosterRow[] = Array.from(driverMap.entries())
        .map(([driverId, data]) => ({
            driver_id: driverId,
            driver_name: data.name,
            driver_type: getDriverType(data.totalHours),
            weekly_hours: data.totalHours,
            shifts: data.shifts,
        }))
        .sort((a, b) => {
            // Sort: FTE first, then by hours descending
            if (a.driver_type !== b.driver_type) {
                const order: Record<DriverType, number> = { 'FTE': 0, 'PT_core': 1, 'PT_flex': 2 };
                return order[a.driver_type] - order[b.driver_type];
            }
            return b.weekly_hours - a.weekly_hours;
        });

    // Build insights
    const insights: RunInsights = {
        total_hours: schedule.stats.total_hours || roster.reduce((sum, r) => sum + r.weekly_hours, 0),
        core_share: schedule.stats.drivers_pt / (schedule.stats.total_drivers || 1) * 100,
        orphans_count: schedule.stats.total_tours_unassigned,
        violation_count: schedule.validation.hard_violations.length,
        drivers_total: schedule.stats.total_drivers,
        drivers_fte: schedule.stats.drivers_fte,
        drivers_pt: schedule.stats.drivers_pt,
        assignment_rate: schedule.stats.assignment_rate,
        avg_utilization: schedule.stats.average_driver_utilization,
        ...schedule.stats.block_counts,
    };

    return {
        id: schedule.id,
        roster,
        insights,
    };
}

// Export for use in API layer
export type { ScheduleResponse };
