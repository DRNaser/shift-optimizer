// =============================================================================
// SOLVEREIGN BFF - Scenarios Endpoint
// =============================================================================
// GET /api/tenant/scenarios - List scenarios
// POST /api/tenant/scenarios - Create new scenario
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import {
  generateTenantIdempotencyKey,
  type RoutingScenario,
} from '@/lib/tenant-api';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

// =============================================================================
// MOCK DATA
// =============================================================================

const MOCK_SCENARIOS: RoutingScenario[] = [
  {
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
    latest_plan_id: 'plan-001',
  },
  {
    id: 'scn-002',
    tenant_code: 'lts-transport',
    site_code: 'wien',
    vertical: 'HDL_PLUS',
    plan_date: '2026-01-07',
    status: 'CREATED',
    input_hash: 'def456',
    stops_count: 180,
    vehicles_count: 12,
    created_at: '2026-01-06T14:30:00Z',
    solved_at: null,
    latest_plan_id: null,
  },
];

// =============================================================================
// HANDLERS
// =============================================================================

export async function GET(request: NextRequest) {
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<RoutingScenario[]>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const scenarios = MOCK_SCENARIOS.filter(
    s => s.tenant_code === tenantCode && s.site_code === siteCode
  );

  return NextResponse.json(scenarios);
}

export async function POST(request: NextRequest) {
  // ==========================================================================
  // RBAC CHECK: create:scenario (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('create:scenario');
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

  try {
    const body = await request.json();
    const { vertical, plan_date } = body;

    if (!vertical || !plan_date) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'vertical and plan_date required' },
        { status: 400 }
      );
    }

    if (!['MEDIAMARKT', 'HDL_PLUS'].includes(vertical)) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'Invalid vertical. Must be MEDIAMARKT or HDL_PLUS' },
        { status: 400 }
      );
    }

    // In production: Call backend with idempotency key
    // const response = await tenantFetch<RoutingScenario>(
    //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios`,
    //   {
    //     tenantCode,
    //     siteCode,
    //     method: 'POST',
    //     body: { vertical, plan_date },
    //     idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'create-scenario', plan_date),
    //   }
    // );

    // Mock: Create new scenario
    const newScenario: RoutingScenario = {
      id: `scn-${Date.now()}`,
      tenant_code: tenantCode,
      site_code: siteCode,
      vertical,
      plan_date,
      status: 'CREATED',
      input_hash: `hash-${Date.now()}`,
      stops_count: 0,
      vehicles_count: 0,
      created_at: new Date().toISOString(),
      solved_at: null,
      latest_plan_id: null,
    };

    return NextResponse.json(newScenario, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { code: 'PARSE_ERROR', message: 'Invalid JSON body' },
      { status: 400 }
    );
  }
}
