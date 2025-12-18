/**
 * Shift Optimizer API Client
 * --------------------------
 * Typed API client for communicating with the backend.
 */

const API_BASE = '/api/v1';

// =============================================================================
// TYPES
// =============================================================================

export type WeekdayFE = 'MONDAY' | 'TUESDAY' | 'WEDNESDAY' | 'THURSDAY' | 'FRIDAY' | 'SATURDAY' | 'SUNDAY';

export interface TourInput {
    id: string;
    day: WeekdayFE;
    start_time: string; // HH:MM
    end_time: string;   // HH:MM
}

export interface ScheduleRequest {
    week_start: string;
    tours: TourInput[];
    solver_type: 'greedy' | 'cpsat' | 'cpsat+lns' | 'cpsat-global' | 'set-partitioning' | 'heuristic';
    time_limit_seconds: number;
    seed?: number;
    lns_iterations?: number;
    target_ftes?: number;
    fte_overflow_cap?: number;
}

export interface TourOutput {
    id: string;
    day: WeekdayFE;
    start_time: string;
    end_time: string;
    duration_hours: number;
}

export interface BlockOutput {
    id: string;
    day: WeekdayFE;
    block_type: 'single' | 'double' | 'triple';
    tours: TourOutput[];
    driver_id: string;
    total_work_hours: number;
    span_hours: number;
}

export interface AssignmentOutput {
    driver_id: string;
    driver_name: string;
    day: WeekdayFE;
    block: BlockOutput;
}

export interface UnassignedTour {
    tour: TourOutput;
    reason: string;
    details?: string;
}

export interface StatsOutput {
    total_drivers: number;
    total_tours_input: number;
    total_tours_assigned: number;
    total_tours_unassigned: number;
    block_counts: { single: number; double: number; triple: number };
    assignment_rate: number;
    average_driver_utilization: number;
    average_work_hours: number;
    block_mix?: Record<string, number>;
    template_match_count?: number;
    split_2er_count?: number;
}

export interface ValidationOutput {
    is_valid: boolean;
    hard_violations: string[];
    warnings: string[];
}

export interface ScheduleResponse {
    id: string;
    week_start: string;
    assignments: AssignmentOutput[];
    unassigned_tours: UnassignedTour[];
    validation: ValidationOutput;
    stats: StatsOutput;
    version: string;
    solver_type: string;
}

export interface HealthResponse {
    status: string;
    version: string;
    constraints: {
        min_hours_per_fte: number;
        max_hours_per_fte: number;
        max_daily_span_hours: number;
    };
}

export interface ConstraintsResponse {
    hard: {
        min_hours_per_fte: number;
        max_hours_per_fte: number;
        max_daily_span_hours: number;
        min_rest_hours: number;
    };
    soft: {
        prefer_larger_blocks: boolean;
        target_2er_ratio: number;
        target_3er_ratio: number;
    };
}

// =============================================================================
// API CALLS
// =============================================================================

export async function fetchHealth(): Promise<HealthResponse> {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
    return res.json();
}

export async function fetchConstraints(): Promise<ConstraintsResponse> {
    const res = await fetch(`${API_BASE}/constraints`);
    if (!res.ok) throw new Error(`Failed to fetch constraints: ${res.status}`);
    return res.json();
}

export async function createSchedule(request: ScheduleRequest): Promise<ScheduleResponse> {
    const res = await fetch(`${API_BASE}/schedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Schedule request failed: ${res.status} - ${detail}`);
    }
    return res.json();
}

/**
 * Connect to the SSE log stream.
 * @param onMessage Callback for each log message
 * @returns EventSource instance (call .close() to disconnect)
 */
export function connectLogStream(onMessage: (msg: string) => void): EventSource {
    console.log('[SSE] Connecting to log stream...');
    const es = new EventSource(`${API_BASE}/logs/stream`);
    es.onopen = () => {
        console.log('[SSE] Connected!');
    };
    es.onmessage = (event) => {
        console.log('[SSE] Raw data:', event.data);
        try {
            // Try to parse as JSON (backend sends {level, message, ts})
            const data = JSON.parse(event.data);
            console.log('[SSE] Parsed:', data);
            if (data.message) {
                onMessage(data.message);
            }
        } catch {
            // If not JSON, use raw data (e.g., keepalive)
            if (event.data && !event.data.startsWith(':')) {
                onMessage(event.data);
            }
        }
    };
    es.onerror = (err) => {
        console.error('[SSE] Error:', err);
    };
    return es;
}
