// =============================================================================
// SOLVEREIGN BFF - Scenario Detail Endpoint
// =============================================================================
// GET /api/tenant/scenarios/[scenarioId] - Get scenario details
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import type { RoutingScenario } from '@/lib/tenant-api';

async function getTenantContext() {
  const cookieStore = await cookies();
  const tenantCode = cookieStore.get('sv_tenant_code')?.value || 'lts-transport';
  const siteCode = cookieStore.get('sv_current_site')?.value || 'wien';
  return { tenantCode, siteCode };
}

// Mock scenarios lookup - includes latest_plan_id per Blueprint v6 Contract
const MOCK_SCENARIOS: Record<string, RoutingScenario> = {
  'scn-001': {
    id: 'scn-001',
    tenant_code: 'lts-transport',
    site_code: 'wien',
    vertical: 'MEDIAMARKT',
    plan_date: '2026-01-06',
    status: 'SOLVED',
    input_hash: 'abc123',
    stops_count: 250,
    vehicles_count: 15,
    created_at: '2026-01-06T06:00:00Z',
    solved_at: '2026-01-06T06:05:32Z',
    latest_plan_id: 'plan-001',  // Backend must provide; null if not solved
  },
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ scenarioId: string }> }
) {
  const { scenarioId } = await params;
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<RoutingScenario>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios/${scenarioId}`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const scenario = MOCK_SCENARIOS[scenarioId];
  if (!scenario) {
    return NextResponse.json(
      { code: 'NOT_FOUND', message: 'Scenario not found' },
      { status: 404 }
    );
  }

  return NextResponse.json(scenario);
}
