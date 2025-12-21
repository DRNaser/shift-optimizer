/**
 * API Client for ShiftOptimizer v2.0
 * 
 * Endpoints:
 * - GET /v1/config-schema
 * - POST /v1/runs
 * - GET /v1/runs/{id}
 * - GET /v1/runs/{id}/events (SSE)
 * - GET /v1/runs/{id}/report
 * - GET /v1/runs/{id}/report/canonical
 * - GET /v1/runs/{id}/plan
 * - POST /v1/runs/{id}/cancel
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api';

// =============================================================================
// TYPES
// =============================================================================

export interface ConfigField {
    key: string;
    type: 'bool' | 'float' | 'int' | 'string';
    default: boolean | number | string | null;
    editable: boolean;
    description: string;
    locked_reason?: string;
    min?: number;
    max?: number;
}

export interface ConfigGroup {
    id: string;
    label: string;
    fields: ConfigField[];
}

export interface ConfigSchema {
    version: string;
    groups: ConfigGroup[];
}

export interface TourInput {
    id: string;
    day: string;
    start_time: string;
    end_time: string;
    location?: string;
    required_qualifications?: string[];
}

export interface RunConfig {
    seed?: number;
    time_budget_seconds: number;
    preset_id?: string;
    config_overrides: Record<string, boolean | number | string>;
}

export interface RunCreateRequest {
    instance_id?: string;
    tours: TourInput[];
    drivers?: any[];
    week_start: string;
    run: RunConfig;
}

export interface RunCreateResponse {
    run_id: string;
    status: string;
    events_url: string;
    run_url: string;
}

export interface RunLinks {
    events: string;
    report: string;
    plan: string;
    canonical_report: string;
    cancel: string;
}

export interface RunStatus {
    run_id: string;
    status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
    phase: string | null;
    budget: {
        total: number;
        slices?: Record<string, number>;
        status: string;
        config_hash?: string;
        overrides_rejected?: Record<string, string>;
    };
    links: RunLinks;
    created_at: string;
}

export interface SSEEvent {
    run_id: string;
    seq: number;
    ts: string;
    level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
    event: string;
    phase: string | null;
    payload: Record<string, any>;
}

export interface RunReport {
    run_id: string;
    input_summary: Record<string, any>;
    pool: { raw: number; dedup: number; capped: number };
    budget: { total: number; slices: Record<string, number>; enforced: boolean };
    timing: { phase1_s: number; phase2_s: number; lns_s: number; total_s: number };
    reason_codes: string[];
    solution_signature: string;
    config?: {
        effective_hash: string;
        overrides_applied: Record<string, any>;
        overrides_rejected: Record<string, string>;
        overrides_clamped: Record<string, [any, any]>;
    };
}

export interface BlockOutput {
    id: string;
    day: string;
    block_type: string;
    tours: any[];
    driver_id: string | null;
    total_work_hours: number;
    span_hours: number;
}

export interface AssignmentOutput {
    driver_id: string;
    driver_name: string;
    day: string;
    block: BlockOutput;
}

export interface PlanResponse {
    id: string;
    week_start: string;
    assignments: AssignmentOutput[];
    unassigned_tours: any[];
    validation: { is_valid: boolean; hard_violations: string[]; warnings: string[] };
    stats: {
        total_drivers: number;
        total_tours_input: number;
        total_tours_assigned: number;
        total_tours_unassigned: number;
        block_counts: Record<string, number>;
        assignment_rate: number;
        average_driver_utilization: number;
        average_work_hours: number;
    };
}

// =============================================================================
// ERROR HANDLING
// =============================================================================

export class ApiError extends Error {
    constructor(
        public status: number,
        public statusText: string,
        public body?: any
    ) {
        super(`API Error: ${status} ${statusText}`);
        this.name = 'ApiError';
    }
}

async function handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
        let body;
        try {
            body = await response.json();
        } catch {
            body = await response.text();
        }
        throw new ApiError(response.status, response.statusText, body);
    }
    return response.json();
}

// =============================================================================
// API FUNCTIONS
// =============================================================================

export async function getConfigSchema(): Promise<ConfigSchema> {
    const response = await fetch(`${API_BASE}/v1/config-schema`);
    return handleResponse<ConfigSchema>(response);
}

export async function createRun(request: RunCreateRequest): Promise<RunCreateResponse> {
    const response = await fetch(`${API_BASE}/v1/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
    });
    return handleResponse<RunCreateResponse>(response);
}

export async function getRunStatus(runId: string): Promise<RunStatus> {
    const response = await fetch(`${API_BASE}/v1/runs/${runId}`);
    return handleResponse<RunStatus>(response);
}

export async function getRunReport(runId: string): Promise<RunReport> {
    const response = await fetch(`${API_BASE}/v1/runs/${runId}/report`);
    return handleResponse<RunReport>(response);
}

export async function getRunReportCanonical(runId: string): Promise<string> {
    const response = await fetch(`${API_BASE}/v1/runs/${runId}/report/canonical`);
    if (!response.ok) {
        throw new ApiError(response.status, response.statusText);
    }
    return response.text();
}

export async function getRunPlan(runId: string): Promise<PlanResponse> {
    const response = await fetch(`${API_BASE}/v1/runs/${runId}/plan`);
    return handleResponse<PlanResponse>(response);
}

export async function cancelRun(runId: string): Promise<{ status: string }> {
    const response = await fetch(`${API_BASE}/v1/runs/${runId}/cancel`, {
        method: 'POST',
    });
    return handleResponse<{ status: string }>(response);
}

// =============================================================================
// SSE HELPER
// =============================================================================

export function createEventSource(
    runId: string,
    onEvent: (event: SSEEvent) => void,
    onError?: (error: Event) => void
): EventSource {
    const url = `${API_BASE}/v1/runs/${runId}/events`;
    const eventSource = new EventSource(url);

    // Handle all event types
    const eventTypes = [
        'run_started', 'run_snapshot', 'phase_started', 'phase_progress',
        'solver_log', 'metric_snapshot', 'warning', 'error',
        'phase_completed', 'run_completed', 'heartbeat', 'run_cancelled'
    ];

    eventTypes.forEach(eventType => {
        eventSource.addEventListener(eventType, (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                onEvent(data);
            } catch {
                console.warn('Failed to parse SSE event:', e.data);
            }
        });
    });

    // Generic message handler for unknown event types
    eventSource.onmessage = (e: MessageEvent) => {
        try {
            const data = JSON.parse(e.data);
            onEvent(data);
        } catch {
            console.warn('Failed to parse SSE message:', e.data);
        }
    };

    eventSource.onerror = (e) => {
        onError?.(e);
    };

    return eventSource;
}

// =============================================================================
// DOWNLOAD HELPERS
// =============================================================================

export function downloadJson(data: any, filename: string) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

export function downloadText(text: string, filename: string) {
    const blob = new Blob([text], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}
