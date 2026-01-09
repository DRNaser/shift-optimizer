// =============================================================================
// SOLVEREIGN BFF - Solve Scenario
// =============================================================================
// POST /api/tenant/scenarios/[scenarioId]/solve
//
// Triggers OR-Tools VRPTW solver for the scenario.
// Returns plan_id for tracking.
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
  { params }: { params: Promise<{ scenarioId: string }> }
) {
  const { scenarioId } = await params;

  // ==========================================================================
  // RBAC CHECK: solve:scenario (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('solve:scenario');
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
  const { tenantCode, siteCode } = await getTenantContext();

  let config = {};
  try {
    config = await request.json();
  } catch {
    // No config provided, use defaults
  }

  // In production: Call backend
  // const response = await tenantFetch<RoutingPlan>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios/${scenarioId}/solve`,
  //   { tenantCode, siteCode, method: 'POST', body: config }
  // );

  // Mock: Create plan in SOLVING status
  const plan: RoutingPlan = {
    id: `plan-${Date.now()}`,
    scenario_id: scenarioId,
    status: 'SOLVING',
    seed: (config as any).seed || 94,
    solver_config_hash: `cfg-${Date.now()}`,
    output_hash: null,
    total_vehicles: null,
    total_distance_km: null,
    total_duration_min: null,
    unassigned_count: null,
    on_time_percentage: null,
    created_at: new Date().toISOString(),
    locked_at: null,
    locked_by: null,
  };

  return NextResponse.json(plan, { status: 202 });
}
