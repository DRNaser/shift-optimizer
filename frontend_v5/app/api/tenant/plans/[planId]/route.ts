// =============================================================================
// SOLVEREIGN BFF - Plan Detail Endpoint
// =============================================================================
// GET /api/tenant/plans/[planId] - Get plan details
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import type { RoutingPlan } from '@/lib/tenant-api';

async function getTenantContext() {
  const cookieStore = await cookies();
  const tenantCode = cookieStore.get('sv_tenant_code')?.value || 'lts-transport';
  const siteCode = cookieStore.get('sv_current_site')?.value || 'wien';
  return { tenantCode, siteCode };
}

// Mock plans
const MOCK_PLANS: Record<string, RoutingPlan> = {
  'plan-001': {
    id: 'plan-001',
    scenario_id: 'scn-001',
    status: 'AUDITED',
    seed: 94,
    solver_config_hash: 'cfg-001',
    output_hash: 'out-abc123',
    total_vehicles: 15,
    total_distance_km: 485.5,
    total_duration_min: 720,
    unassigned_count: 2,
    on_time_percentage: 96.8,
    created_at: '2026-01-06T06:05:32Z',
    locked_at: null,
    locked_by: null,
  },
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<RoutingPlan>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const plan = MOCK_PLANS[planId];
  if (!plan) {
    return NextResponse.json(
      { code: 'NOT_FOUND', message: 'Plan not found' },
      { status: 404 }
    );
  }

  return NextResponse.json(plan);
}
