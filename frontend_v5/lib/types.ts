export type ShiftType = '3er' | '2er' | '2er_split' | '1er';
export type DriverType = 'FTE' | 'PT_core' | 'PT_flex';

export interface Shift {
    day_index: number; // 0=Mon, 5=Sat
    start_time: string; // "08:00"
    end_time: string;   // "17:00"
    type: ShiftType;
    is_split: boolean;
}

export interface RosterRow {
    driver_id: string;
    driver_name: string;
    driver_type: DriverType;
    weekly_hours: number;
    // Array must always have length 6 (Mon-Sat), null if off
    shifts: (Shift | null)[];
}

export interface RunInsights {
    total_hours: number;
    core_share: number;
    orphans_count: number;
    violation_count: number;
    // Fleet Counter metrics (v7.2.0)
    fleet_peak_count?: number;
    fleet_peak_day?: string;
    fleet_peak_time?: string;
    // Add dynamic keys if necessary
    [key: string]: number | string | undefined;
}

export interface RunDetailData {
    id: string;
    roster: RosterRow[];
    insights: RunInsights;
}
