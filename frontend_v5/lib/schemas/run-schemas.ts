/**
 * SOLVEREIGN - Zod Schemas for Run API Responses
 *
 * Runtime validation ensures:
 * 1. run_id is always present in responses
 * 2. Required fields are validated before UI renders
 * 3. Discriminated unions for status-based rendering
 */

import { z } from "zod";

// =============================================================================
// RUN CREATE RESPONSE
// =============================================================================

export const RunCreateResponseSchema = z.object({
    run_id: z.string().uuid({ message: "run_id must be a valid UUID" }),
    status: z.string(),
    run_url: z.string().optional(),
});

export type RunCreateResponse = z.infer<typeof RunCreateResponseSchema>;

// =============================================================================
// RUN STATUS RESPONSE (Discriminated Union)
// =============================================================================

const BaseRunStatusSchema = z.object({
    run_id: z.string().uuid({ message: "run_id must be a valid UUID" }),
    phase: z.string().optional(),
    budget: z.object({
        total: z.number(),
        status: z.string(),
    }).optional(),
});

export const RunStatusQueuedSchema = BaseRunStatusSchema.extend({
    status: z.literal("QUEUED"),
});

export const RunStatusRunningSchema = BaseRunStatusSchema.extend({
    status: z.literal("RUNNING"),
});

export const RunStatusCompletedSchema = BaseRunStatusSchema.extend({
    status: z.literal("COMPLETED"),
});

export const RunStatusFailedSchema = BaseRunStatusSchema.extend({
    status: z.literal("FAILED"),
    error_code: z.string().optional(),
    error_message: z.string().optional(),
    trace_id: z.string().optional(),
});

export const RunStatusCancelledSchema = BaseRunStatusSchema.extend({
    status: z.literal("CANCELLED"),
});

export const RunStatusResponseSchema = z.discriminatedUnion("status", [
    RunStatusQueuedSchema,
    RunStatusRunningSchema,
    RunStatusCompletedSchema,
    RunStatusFailedSchema,
    RunStatusCancelledSchema,
]);

export type RunStatusResponse = z.infer<typeof RunStatusResponseSchema>;
export type RunStatusQueued = z.infer<typeof RunStatusQueuedSchema>;
export type RunStatusRunning = z.infer<typeof RunStatusRunningSchema>;
export type RunStatusCompleted = z.infer<typeof RunStatusCompletedSchema>;
export type RunStatusFailed = z.infer<typeof RunStatusFailedSchema>;
export type RunStatusCancelled = z.infer<typeof RunStatusCancelledSchema>;

// =============================================================================
// SCHEDULE RESPONSE (Run Result)
// =============================================================================

export const BlockOutputSchema = z.object({
    id: z.string(),
    day: z.string(),
    block_type: z.string(),
    tours: z.array(z.object({
        id: z.string(),
        day: z.string(),
        start_time: z.string(),
        end_time: z.string(),
        duration_hours: z.number(),
    })),
    driver_id: z.string().nullable(),
    total_work_hours: z.number(),
    span_hours: z.number(),
    pause_zone: z.string(),
});

export const AssignmentOutputSchema = z.object({
    driver_id: z.string(),
    driver_name: z.string(),
    day: z.string(),
    block: BlockOutputSchema.nullable().optional(), // Allow null/undefined blocks for defensive handling
});

export const StatsOutputSchema = z.object({
    total_drivers: z.number(),
    total_tours_input: z.number(),
    total_tours_assigned: z.number(),
    total_tours_unassigned: z.number(),
    block_counts: z.record(z.string(), z.number()).optional(),
    assignment_rate: z.number(),
    average_driver_utilization: z.number(),
    average_work_hours: z.number().optional(),
    drivers_fte: z.number(),
    drivers_pt: z.number(),
    total_hours: z.number().optional(),
    fleet_peak_count: z.number().optional(),
    fleet_peak_day: z.string().optional(),
    fleet_peak_time: z.string().optional(),
    fleet_total_tours: z.number().optional(),
    fleet_day_peaks: z.record(z.string(), z.object({
        count: z.number(),
        time: z.string(),
    })).optional(),
});

export const ScheduleResponseSchema = z.object({
    id: z.string(),
    week_start: z.string(),
    assignments: z.array(AssignmentOutputSchema),
    unassigned_tours: z.array(z.object({
        tour: z.object({
            id: z.string(),
            day: z.string(),
            start_time: z.string(),
            end_time: z.string(),
        }),
        reason_codes: z.array(z.string()),
        details: z.string(),
    })),
    stats: StatsOutputSchema,
    validation: z.object({
        is_valid: z.boolean(),
        hard_violations: z.array(z.string()),
    }),
});

export type ScheduleResponse = z.infer<typeof ScheduleResponseSchema>;

// =============================================================================
// VALIDATION HELPERS
// =============================================================================

/**
 * Validate and parse run create response with helpful error messages
 */
export function parseRunCreateResponse(data: unknown): RunCreateResponse {
    const result = RunCreateResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid run create response:", result.error.flatten());
        throw new Error(`Invalid run response: ${result.error.issues[0]?.message || "Unknown validation error"}`);
    }
    return result.data;
}

/**
 * Validate and parse run status response
 * Returns discriminated union for type-safe status handling
 */
export function parseRunStatusResponse(data: unknown): RunStatusResponse {
    const result = RunStatusResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid run status response:", result.error.flatten());
        // Fallback: return raw data with status for graceful degradation
        const rawData = data as { run_id?: string; status?: string };
        return {
            run_id: rawData.run_id || "unknown",
            status: "FAILED" as const,
            error_code: "VALIDATION_ERROR",
            error_message: `Response validation failed: ${result.error.issues[0]?.message}`,
        };
    }
    return result.data;
}

/**
 * Validate and parse schedule response
 */
export function parseScheduleResponse(data: unknown): ScheduleResponse {
    const result = ScheduleResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid schedule response:", result.error.flatten());
        throw new Error(`Invalid schedule response: ${result.error.issues[0]?.message || "Unknown validation error"}`);
    }
    return result.data;
}

/**
 * Type guard for failed runs
 */
export function isRunFailed(status: RunStatusResponse): status is RunStatusFailed {
    return status.status === "FAILED";
}

/**
 * Type guard for completed runs
 */
export function isRunCompleted(status: RunStatusResponse): status is RunStatusCompleted {
    return status.status === "COMPLETED";
}

/**
 * Type guard for running/queued runs (in progress)
 */
export function isRunInProgress(status: RunStatusResponse): status is RunStatusRunning | RunStatusQueued {
    return status.status === "RUNNING" || status.status === "QUEUED";
}
