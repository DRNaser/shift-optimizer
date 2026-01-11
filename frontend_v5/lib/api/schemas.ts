/**
 * API Response Schemas (Zod)
 * ==========================
 *
 * Type-safe validation for critical backend responses.
 *
 * REQUIREMENTS:
 * - Validate all critical responses before use
 * - Log validation errors without exposing secrets
 * - Return clear error messages to UI
 */

import { z } from 'zod';

// =============================================================================
// ROSTER PLAN SCHEMAS
// =============================================================================

export const PlanSummarySchema = z.object({
  id: z.number(),
  status: z.string(),
  plan_state: z.string(),
  forecast_version_id: z.number().nullable(),
  seed: z.number(),
  output_hash: z.string().nullable(),
  audit_passed_count: z.number(),
  audit_failed_count: z.number(),
  current_snapshot_id: z.number().nullable(),
  publish_count: z.number(),
  created_at: z.string(),
});

export const PlanListResponseSchema = z.object({
  success: z.boolean(),
  plans: z.array(PlanSummarySchema),
  total: z.number(),
});

export const AuditEventSchema = z.object({
  action: z.string().nullable(),
  from_state: z.string().nullable(),
  to_state: z.string().nullable(),
  performed_by: z.string(),
  reason: z.string().nullable(),
  created_at: z.string().nullable(),
});

export const SnapshotInfoSchema = z.object({
  snapshot_id: z.string(),
  version_number: z.number(),
  status: z.string(),
  published_at: z.string().nullable(),
  published_by: z.string(),
});

export const PlanDetailResponseSchema = z.object({
  success: z.boolean(),
  plan: PlanSummarySchema,
  assignments_count: z.number(),
  snapshots: z.array(SnapshotInfoSchema),
  evidence_ref: z.string().nullable(),
  audit_events: z.array(AuditEventSchema),
});

// =============================================================================
// ROSTER SNAPSHOT SCHEMAS
// =============================================================================

export const SnapshotSummarySchema = z.object({
  id: z.number(),
  snapshot_id: z.string(),
  plan_version_id: z.number(),
  version_number: z.number(),
  status: z.string(),
  published_at: z.string(),
  published_by: z.string(),
  publish_reason: z.string().nullable(),
  freeze_until: z.string(),
  is_frozen: z.boolean(),
});

export const SnapshotListResponseSchema = z.object({
  success: z.boolean(),
  snapshots: z.array(SnapshotSummarySchema),
  total: z.number(),
});

export const SnapshotHashesSchema = z.object({
  input_hash: z.string().nullable(),
  matrix_hash: z.string().nullable(),
  output_hash: z.string().nullable(),
  evidence_hash: z.string().nullable(),
});

export const SnapshotDetailResponseSchema = z.object({
  success: z.boolean(),
  snapshot: SnapshotSummarySchema,
  kpi_snapshot: z.record(z.string(), z.unknown()).nullable(),
  assignments_count: z.number(),
  hashes: SnapshotHashesSchema,
  evidence_ref: z.string().nullable(),
});

export const SnapshotPublishResponseSchema = z.object({
  success: z.boolean(),
  snapshot_id: z.string(),
  version_number: z.number(),
  evidence_ref: z.string().nullable(),
});

// =============================================================================
// EVIDENCE SCHEMAS
// =============================================================================

export const EvidenceRecordSchema = z.object({
  id: z.number(),
  plan_version_id: z.number(),
  matrix_version: z.string(),
  matrix_hash: z.string(),
  finalize_verdict: z.string(),
  created_at: z.string(),
  has_drift_report: z.boolean(),
  has_tw_validation: z.boolean(),
});

export const EvidenceListResponseSchema = z.object({
  success: z.boolean(),
  evidence: z.array(EvidenceRecordSchema),
  total: z.number(),
});

export const LocalEvidenceFileSchema = z.object({
  filename: z.string(),
  event_type: z.string(),
  tenant_id: z.number().nullable(),
  site_id: z.number().nullable(),
  entity_id: z.number().nullable(),
  created_at: z.string(),
  size_bytes: z.number(),
});

export const LocalEvidenceListResponseSchema = z.object({
  success: z.boolean(),
  files: z.array(LocalEvidenceFileSchema),
  total: z.number(),
});

// =============================================================================
// AUDIT LOG SCHEMAS
// =============================================================================

export const AuditLogEntrySchema = z.object({
  id: z.number(),
  event_type: z.string(),
  user_id: z.string().nullable(),
  user_email: z.string().nullable(),
  tenant_id: z.number().nullable(),
  target_tenant_id: z.number().nullable(),
  details: z.record(z.string(), z.unknown()).nullable(),
  ip_address: z.string().nullable(),
  user_agent: z.string().nullable(),
  created_at: z.string(),
});

export const AuditLogListResponseSchema = z.object({
  success: z.boolean(),
  entries: z.array(AuditLogEntrySchema),
  total: z.number(),
});

export const AuditEventTypesResponseSchema = z.object({
  success: z.boolean(),
  event_types: z.array(z.string()),
});

// =============================================================================
// REPAIR SCHEMAS (V4.8.1 - Hardened with Violations)
// =============================================================================

export const AssignmentDiffSchema = z.object({
  tour_instance_id: z.number(),
  driver_id: z.number().nullable(),
  new_driver_id: z.number().nullable(),
  day: z.number(),
  block_id: z.string(),
  shift_start: z.string().nullable(),
  shift_end: z.string().nullable(),
  reason: z.string(),
});

export const ViolationEntrySchema = z.object({
  type: z.string(), // 'overlap', 'rest', 'freeze'
  driver_id: z.number().nullable(),
  tour_instance_id: z.number().nullable(),
  conflicting_tour_id: z.number().nullable(),
  message: z.string(),
  severity: z.enum(['BLOCK', 'WARN']),
});

export const ViolationsListSchema = z.object({
  overlap: z.array(ViolationEntrySchema),
  rest: z.array(ViolationEntrySchema),
  freeze: z.array(ViolationEntrySchema),
});

export const IdempotencyInfoSchema = z.object({
  key: z.string(),
  request_hash: z.string(),
});

export const RepairSummarySchema = z.object({
  uncovered_before: z.number(),
  uncovered_after: z.number(),
  churn_driver_count: z.number(),
  churn_assignment_count: z.number(),
  freeze_violations: z.number(),
  overlap_violations: z.number(),
  rest_violations: z.number(),
  absent_drivers_count: z.number(),
});

export const RepairDiffSchema = z.object({
  removed_assignments: z.array(AssignmentDiffSchema),
  added_assignments: z.array(AssignmentDiffSchema),
  modified_assignments: z.array(AssignmentDiffSchema),
});

export const RepairPreviewResponseSchema = z.object({
  success: z.boolean(),
  verdict: z.enum(['OK', 'WARN', 'BLOCK']),
  verdict_reasons: z.array(z.string()),
  summary: RepairSummarySchema,
  violations: ViolationsListSchema,
  diff: RepairDiffSchema,
  evidence_id: z.string(),
  policy_hash: z.string(),
  seed: z.number(),
  base_plan_version_id: z.number(),
  preview_computed_at: z.string(),
});

export const RepairCommitResponseSchema = z.object({
  success: z.boolean(),
  new_plan_version_id: z.number(),
  parent_plan_version_id: z.number(),
  verdict: z.string(),
  summary: RepairSummarySchema,
  violations: ViolationsListSchema,
  idempotency: IdempotencyInfoSchema,
  evidence_id: z.string(),
  evidence_ref: z.string(),
  committed_by: z.string(),
  committed_at: z.string(),
  message: z.string(),
});

// Type exports for Repair
export type RepairPreviewResponse = z.infer<typeof RepairPreviewResponseSchema>;
export type RepairCommitResponse = z.infer<typeof RepairCommitResponseSchema>;
export type RepairSummary = z.infer<typeof RepairSummarySchema>;
export type AssignmentDiff = z.infer<typeof AssignmentDiffSchema>;
export type ViolationEntry = z.infer<typeof ViolationEntrySchema>;
export type ViolationsList = z.infer<typeof ViolationsListSchema>;
export type IdempotencyInfo = z.infer<typeof IdempotencyInfoSchema>;

// =============================================================================
// VALIDATION HELPER
// =============================================================================

export interface ValidationResult<T> {
  success: boolean;
  data?: T;
  error?: string;
}

/**
 * Validate backend response against a schema.
 *
 * @param schema - Zod schema to validate against
 * @param data - Data to validate
 * @param context - Context for logging (e.g., endpoint name)
 * @returns Validation result with typed data or error message
 */
export function validateResponse<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
  context: string
): ValidationResult<T> {
  try {
    const parsed = schema.parse(data);
    return { success: true, data: parsed };
  } catch (error) {
    if (error instanceof z.ZodError) {
      // Log validation error without exposing sensitive data
      console.error(`[VALIDATION] ${context} failed:`, {
        issues: error.issues.map((i) => ({
          path: i.path.join('.'),
          code: i.code,
          message: i.message,
        })),
      });

      return {
        success: false,
        error: `Invalid response from server. Please try again or contact support.`,
      };
    }

    console.error(`[VALIDATION] ${context} unexpected error:`, error);
    return {
      success: false,
      error: 'An unexpected error occurred.',
    };
  }
}

/**
 * Type-safe fetch wrapper that validates responses.
 *
 * @param url - URL to fetch
 * @param schema - Zod schema for response validation
 * @param options - Fetch options
 * @returns Validated response data or throws
 */
export async function fetchAndValidate<T>(
  url: string,
  schema: z.ZodSchema<T>,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(url, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || data.detail || `HTTP ${response.status}`);
  }

  const result = validateResponse(schema, data, url);
  if (!result.success) {
    throw new Error(result.error);
  }

  return result.data!;
}
