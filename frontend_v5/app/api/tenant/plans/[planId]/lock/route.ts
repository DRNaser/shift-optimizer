// =============================================================================
// SOLVEREIGN BFF - Lock Plan Endpoint
// =============================================================================
// POST /api/tenant/plans/[planId]/lock
//
// RBAC: Only APPROVER or TENANT_ADMIN can lock plans.
// AUDIT GATE: Plan can only be locked if ALL audits PASS.
// IDEMPOTENCY: Required for safe retry.
//
// Returns:
// - 200: Plan locked successfully
// - 400: Missing idempotency key
// - 403: Permission denied (PLANNER cannot lock)
// - 409: Audit gate blocked (FAIL audits exist)
// - 503: Tenant blocked
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import type { RoutingPlan } from '@/lib/tenant-api';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;

  // ==========================================================================
  // RBAC CHECK: Only APPROVER+ can lock
  // ==========================================================================
  const permissionDenied = await requirePermission('lock:plan');
  if (permissionDenied) return permissionDenied;

  // ==========================================================================
  // IDEMPOTENCY KEY CHECK
  // ==========================================================================
  const idempotencyKey = request.headers.get('X-Idempotency-Key');
  const idempotencyError = requireIdempotencyKey(idempotencyKey);
  if (idempotencyError) return idempotencyError;

  // ==========================================================================
  // GET TENANT CONTEXT
  // ==========================================================================
  const { tenantCode, siteCode, userEmail } = await getTenantContext();

  // ==========================================================================
  // CALL BACKEND (with audit gate enforcement)
  // ==========================================================================

  // In production: Call backend - backend enforces audit gate
  // const response = await tenantFetch<RoutingPlan>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/lock`,
  //   {
  //     tenantCode,
  //     siteCode,
  //     method: 'POST',
  //     idempotencyKey,
  //   }
  // );
  //
  // // Audit gate blocked
  // if (response.status === 409) {
  //   return NextResponse.json(
  //     {
  //       code: 'AUDIT_GATE_BLOCKED',
  //       message: 'Plan cannot be locked - audit failures exist',
  //       details: response.error?.details,
  //     },
  //     { status: 409 }
  //   );
  // }
  //
  // // Other errors
  // if (!response.data) {
  //   return NextResponse.json(
  //     { code: response.error?.code, message: response.error?.message },
  //     { status: response.status }
  //   );
  // }
  //
  // return NextResponse.json(response.data);

  // ==========================================================================
  // MOCK: Simulate successful lock
  // ==========================================================================
  const lockedPlan: RoutingPlan = {
    id: planId,
    scenario_id: 'scn-001',
    status: 'LOCKED',
    seed: 94,
    solver_config_hash: 'cfg-001',
    output_hash: 'out-abc123',
    total_vehicles: 15,
    total_distance_km: 485.5,
    total_duration_min: 720,
    unassigned_count: 2,
    on_time_percentage: 96.8,
    created_at: '2026-01-06T06:05:32Z',
    locked_at: new Date().toISOString(),
    locked_by: userEmail,
  };

  return NextResponse.json(lockedPlan);
}
