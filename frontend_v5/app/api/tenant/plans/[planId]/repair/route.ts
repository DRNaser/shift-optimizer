// =============================================================================
// SOLVEREIGN BFF - Repair Endpoint
// =============================================================================
// GET /api/tenant/plans/[planId]/repair - List repair events
// POST /api/tenant/plans/[planId]/repair - Create repair event
//
// Repair events trigger re-optimization for:
// - NO_SHOW: Driver/stop no-show
// - DELAY: Significant delay detected
// - VEHICLE_DOWN: Vehicle breakdown
// - MANUAL: Manual reassignment request
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import type { RepairEvent } from '@/lib/tenant-api';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

// Mock repair events
const MOCK_REPAIRS: Record<string, RepairEvent[]> = {
  'plan-001': [
    {
      id: 'rep-001',
      plan_id: 'plan-001',
      event_type: 'NO_SHOW',
      affected_stop_ids: ['stop-045'],
      initiated_by: 'dispatcher@lts.de',
      initiated_at: '2026-01-06T10:30:00Z',
      repair_plan_id: 'plan-002',
      status: 'COMPLETED',
    },
  ],
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<RepairEvent[]>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/repair`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const repairs = MOCK_REPAIRS[planId] || [];
  return NextResponse.json(repairs);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;

  // ==========================================================================
  // RBAC CHECK: create:repair (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('create:repair');
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
    const body = await request.json();
    const { event_type, affected_stop_ids } = body;

    if (!event_type || !affected_stop_ids) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'event_type and affected_stop_ids required' },
        { status: 400 }
      );
    }

    if (!['NO_SHOW', 'DELAY', 'VEHICLE_DOWN', 'MANUAL'].includes(event_type)) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'Invalid event_type' },
        { status: 400 }
      );
    }

    // In production: Call backend
    // const response = await tenantFetch<RepairEvent>(
    //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/repair`,
    //   { tenantCode, siteCode, method: 'POST', body: { event_type, affected_stop_ids } }
    // );

    // Mock: Create repair event
    const repair: RepairEvent = {
      id: `rep-${Date.now()}`,
      plan_id: planId,
      event_type,
      affected_stop_ids,
      initiated_by: userEmail,
      initiated_at: new Date().toISOString(),
      repair_plan_id: null,
      status: 'PENDING',
    };

    return NextResponse.json(repair, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { code: 'PARSE_ERROR', message: 'Invalid JSON body' },
      { status: 400 }
    );
  }
}
