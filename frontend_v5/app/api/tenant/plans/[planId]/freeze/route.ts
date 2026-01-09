// =============================================================================
// SOLVEREIGN BFF - Plan Freeze
// =============================================================================
// GET /api/tenant/plans/[planId]/freeze - Get freeze state
// POST /api/tenant/plans/[planId]/freeze - Apply manual freeze
//
// FREEZE vs LOCK:
// - LOCK: Immutability of plan version (prevents modifications)
// - FREEZE: Operational protection (time-based, prevents reassignments)
//
// Freeze is enforced at:
// - Default: 60 minutes before stop start time
// - Manual: Can be applied earlier by APPROVER
//
// Frozen stops CANNOT be:
// - Reassigned to different vehicle
// - Resequenced within route
// - Removed from plan
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

interface FreezeState {
  plan_id: string;
  total_stops: number;
  frozen_stops: number;
  unfrozen_stops: number;
  freeze_horizon_minutes: number;
  frozen_stop_ids: string[];
  manually_frozen: string[];
  time_frozen: string[];
  freeze_status: 'NONE' | 'PARTIAL' | 'FULL';
  next_freeze_at: string | null;
}

interface ManualFreezeRequest {
  stop_ids: string[];
  reason: string;
}

interface ManualFreezeResponse {
  plan_id: string;
  frozen_count: number;
  frozen_stop_ids: string[];
  frozen_by: string;
  frozen_at: string;
}


// GET: Fetch freeze state
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<FreezeState>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/freeze`,
  //   { tenantCode, siteCode }
  // );

  // Mock freeze state
  const now = new Date();
  const freezeState: FreezeState = {
    plan_id: planId,
    total_stops: 50,
    frozen_stops: 12,
    unfrozen_stops: 38,
    freeze_horizon_minutes: 60,
    frozen_stop_ids: [
      'stop-001', 'stop-002', 'stop-003', 'stop-004',
      'stop-005', 'stop-006', 'stop-007', 'stop-008',
      'stop-009', 'stop-010', 'stop-011', 'stop-012',
    ],
    manually_frozen: ['stop-001', 'stop-002'],
    time_frozen: [
      'stop-003', 'stop-004', 'stop-005', 'stop-006',
      'stop-007', 'stop-008', 'stop-009', 'stop-010',
      'stop-011', 'stop-012',
    ],
    freeze_status: 'PARTIAL',
    next_freeze_at: new Date(now.getTime() + 15 * 60 * 1000).toISOString(), // 15 min
  };

  return NextResponse.json(freezeState);
}

// POST: Apply manual freeze
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;

  // ==========================================================================
  // RBAC CHECK: Only APPROVER+ can freeze (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('freeze:stops');
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

  try {
    const body: ManualFreezeRequest = await request.json();
    const { stop_ids, reason } = body;

    if (!stop_ids || stop_ids.length === 0) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'stop_ids array required' },
        { status: 400 }
      );
    }

    if (!reason) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'reason required for manual freeze' },
        { status: 400 }
      );
    }

    // In production: Call backend
    // const response = await tenantFetch<ManualFreezeResponse>(
    //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/freeze`,
    //   {
    //     tenantCode,
    //     siteCode,
    //     method: 'POST',
    //     body: { stop_ids, reason },
    //     idempotencyKey,
    //   }
    // );

    // Mock response
    const freezeResponse: ManualFreezeResponse = {
      plan_id: planId,
      frozen_count: stop_ids.length,
      frozen_stop_ids: stop_ids,
      frozen_by: userEmail,
      frozen_at: new Date().toISOString(),
    };

    return NextResponse.json(freezeResponse, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { code: 'PARSE_ERROR', message: 'Invalid JSON body' },
      { status: 400 }
    );
  }
}
