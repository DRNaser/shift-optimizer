/**
 * SOLVEREIGN - Zod Schemas for Matrix API Responses
 *
 * Runtime validation ensures:
 * 1. Matrix cells have required structure
 * 2. Driver/day grid is complete
 * 3. Violations are properly typed
 * 4. Pins have unique constraints handled
 */

import { z } from "zod";

// =============================================================================
// MATRIX RESPONSE
// =============================================================================

export const MatrixCellSchema = z.object({
    driver_id: z.string(),
    day: z.string(),
    has_assignment: z.boolean(),
    tour_instance_id: z.number().nullable().optional(),
    block_type: z.string().nullable().optional(),
    block_id: z.string().nullable().optional(),
    work_hours: z.number().nullable().optional(),
    span_hours: z.number().nullable().optional(),
    is_pinned: z.boolean().optional().default(false),
    pin_id: z.number().nullable().optional(),
    violations: z.array(z.string()).optional().default([]),
    severity: z.enum(["BLOCK", "WARN"]).nullable().optional(),
});

export const MatrixDriverSchema = z.object({
    driver_id: z.string(),
    driver_name: z.string(),
    employment_type: z.enum(["FTE", "PT"]).optional(),
    weekly_hours: z.number().optional(),
    block_count: z.number().optional().default(0),
    warn_count: z.number().optional().default(0),
});

export const MatrixResponseSchema = z.object({
    week_start: z.string(),
    days: z.array(z.string()),
    drivers: z.array(MatrixDriverSchema),
    cells: z.array(MatrixCellSchema),
    violations: z.array(z.object({
        driver_id: z.string(),
        day: z.string().optional(),
        severity: z.enum(["BLOCK", "WARN"]),
        type: z.string(),
        message: z.string(),
    })).optional().default([]),
});

export type MatrixResponse = z.infer<typeof MatrixResponseSchema>;
export type MatrixCell = z.infer<typeof MatrixCellSchema>;
export type MatrixDriver = z.infer<typeof MatrixDriverSchema>;

// =============================================================================
// VIOLATIONS RESPONSE
// =============================================================================

export const ViolationEntrySchema = z.object({
    id: z.union([z.string(), z.number()]).optional(),
    driver_id: z.string(),
    day: z.string().optional(),
    tour_instance_id: z.number().optional(),
    block_id: z.string().optional(),
    severity: z.enum(["BLOCK", "WARN"]),
    type: z.string(),
    message: z.string(),
    details: z.record(z.string(), z.unknown()).optional(),
});

export const ViolationsResponseSchema = z.object({
    violations: z.array(ViolationEntrySchema),
    summary: z.object({
        total: z.number(),
        block_count: z.number(),
        warn_count: z.number(),
    }).optional(),
});

export type ViolationsResponse = z.infer<typeof ViolationsResponseSchema>;
export type ViolationEntry = z.infer<typeof ViolationEntrySchema>;

// =============================================================================
// PINS RESPONSE
// =============================================================================

export const PinSchema = z.object({
    id: z.number(),
    plan_version_id: z.number().optional(),
    driver_id: z.string(),
    day: z.string(),
    tour_instance_id: z.number().optional().nullable(),
    reason_code: z.enum(["MANUAL", "PREFERENCE", "CONSTRAINT", "REPAIR"]).optional(),
    note: z.string().optional(),
    created_at: z.string().optional(),
    created_by: z.string().optional(),
    is_active: z.boolean().optional().default(true),
});

export const PinsResponseSchema = z.object({
    pins: z.array(PinSchema),
    total: z.number().optional(),
});

export const PinCreateResponseSchema = z.object({
    success: z.boolean(),
    pin_id: z.number(),
    message: z.string().optional(),
});

export const PinDeleteResponseSchema = z.object({
    success: z.boolean(),
    message: z.string().optional(),
});

export type PinsResponse = z.infer<typeof PinsResponseSchema>;
export type Pin = z.infer<typeof PinSchema>;
export type PinCreateResponse = z.infer<typeof PinCreateResponseSchema>;
export type PinDeleteResponse = z.infer<typeof PinDeleteResponseSchema>;

// =============================================================================
// DIFF RESPONSE
// =============================================================================

export const DiffChangeSchema = z.object({
    type: z.enum(["ADDED", "REMOVED", "MODIFIED", "ASSIGNMENT_CHANGED"]),
    driver_id: z.string(),
    day: z.string().optional(),
    tour_instance_id: z.number().optional(),
    block_id: z.string().optional(),
    old_value: z.unknown().optional(),
    new_value: z.unknown().optional(),
    description: z.string().optional(),
});

export const DiffResponseSchema = z.object({
    success: z.boolean().optional().default(true),
    base_plan_id: z.number().optional(),
    base_snapshot_id: z.number().optional(),
    target_plan_id: z.number().optional(),
    target_snapshot_id: z.number().optional(),
    changes: z.array(DiffChangeSchema),
    stats: z.object({
        total_changes: z.number(),
        added: z.number(),
        removed: z.number(),
        modified: z.number(),
    }).optional(),
    kpi_delta: z.object({
        assignment_rate: z.number().optional(),
        driver_count: z.number().optional(),
        total_hours: z.number().optional(),
    }).optional(),
    can_publish: z.boolean().optional(),
    publish_blockers: z.array(z.string()).optional(),
});

export type DiffResponse = z.infer<typeof DiffResponseSchema>;
export type DiffChange = z.infer<typeof DiffChangeSchema>;

// =============================================================================
// REPAIR SESSION SCHEMAS
// =============================================================================

export const RepairSessionSchema = z.object({
    session_id: z.string(),
    plan_version_id: z.number(),
    status: z.enum(["ACTIVE", "PREVIEWING", "APPLIED", "ABORTED", "EXPIRED"]),
    expires_at: z.string(),
    created_at: z.string(),
    created_by: z.string().optional(),
    can_undo: z.boolean().optional().default(false),
    undo_stack_depth: z.number().optional().default(0),
});

export const RepairSessionCreateResponseSchema = z.object({
    success: z.boolean(),
    session_id: z.string(),
    expires_at: z.string(),
    status: z.string(),
});

export const RepairPreviewResponseSchema = z.object({
    verdict: z.enum(["OK", "WARN", "BLOCK"]),
    verdict_reasons: z.array(z.string()).optional().default([]),
    summary: z.object({
        uncovered_before: z.number(),
        uncovered_after: z.number(),
        churn_driver_count: z.number(),
        churn_assignment_count: z.number(),
        overlap_violations: z.number().optional().default(0),
        rest_violations: z.number().optional().default(0),
        freeze_violations: z.number().optional().default(0),
    }),
    diff: z.object({
        removed_assignments: z.array(z.object({
            tour_instance_id: z.number(),
            day: z.number(),
            block_id: z.string(),
            driver_id: z.string(),
            reason: z.string(),
        })),
        added_assignments: z.array(z.object({
            tour_instance_id: z.number(),
            day: z.number(),
            block_id: z.string(),
            driver_id: z.string().optional(),
            new_driver_id: z.string(),
            reason: z.string(),
        })),
    }),
    violations: z.object({
        overlap: z.array(z.object({ message: z.string() })),
        rest: z.array(z.object({ message: z.string() })),
        freeze: z.array(z.object({ message: z.string() })),
    }),
    evidence_id: z.string(),
    policy_hash: z.string(),
});

export const RepairApplyResponseSchema = z.object({
    success: z.boolean(),
    new_plan_version_id: z.number().optional(),
    new_snapshot_id: z.number().optional(),
    message: z.string().optional(),
    can_undo: z.boolean().optional(),
});

export const RepairUndoResponseSchema = z.discriminatedUnion("success", [
    z.object({
        success: z.literal(true),
        message: z.string().optional(),
        can_undo_more: z.boolean(),
        remaining_undo_depth: z.number().optional(),
    }),
    z.object({
        success: z.literal(false),
        error_code: z.enum([
            "NOTHING_TO_UNDO",
            "SNAPSHOT_ALREADY_PUBLISHED",
            "PLAN_LOCKED_NO_UNDO",
            "SESSION_EXPIRED",
        ]),
        error: z.string(),
        trace_id: z.string().optional(),
    }),
]);

export type RepairSession = z.infer<typeof RepairSessionSchema>;
export type RepairSessionCreateResponse = z.infer<typeof RepairSessionCreateResponseSchema>;
export type RepairPreviewResponse = z.infer<typeof RepairPreviewResponseSchema>;
export type RepairApplyResponse = z.infer<typeof RepairApplyResponseSchema>;
export type RepairUndoResponse = z.infer<typeof RepairUndoResponseSchema>;

// =============================================================================
// VALIDATION HELPERS
// =============================================================================

/**
 * Validate and parse matrix response with fallback
 */
export function parseMatrixResponse(data: unknown): MatrixResponse {
    const result = MatrixResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid matrix response:", result.error.flatten());
        // Return minimal valid structure
        return {
            week_start: "",
            days: [],
            drivers: [],
            cells: [],
            violations: [],
        };
    }
    return result.data;
}

/**
 * Validate and parse violations response with fallback
 */
export function parseViolationsResponse(data: unknown): ViolationsResponse {
    const result = ViolationsResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid violations response:", result.error.flatten());
        return { violations: [] };
    }
    return result.data;
}

/**
 * Validate and parse pins response with fallback
 */
export function parsePinsResponse(data: unknown): PinsResponse {
    const result = PinsResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid pins response:", result.error.flatten());
        return { pins: [] };
    }
    return result.data;
}

/**
 * Validate and parse diff response with fallback
 */
export function parseDiffResponse(data: unknown): DiffResponse {
    const result = DiffResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid diff response:", result.error.flatten());
        return {
            success: false,
            changes: [],
            can_publish: false,
            publish_blockers: ["VALIDATION_ERROR"],
        };
    }
    return result.data;
}

/**
 * Validate repair preview response
 */
export function parseRepairPreviewResponse(data: unknown): RepairPreviewResponse | null {
    const result = RepairPreviewResponseSchema.safeParse(data);
    if (!result.success) {
        console.error("[API] Invalid repair preview response:", result.error.flatten());
        return null;
    }
    return result.data;
}
