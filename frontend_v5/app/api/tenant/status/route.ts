// =============================================================================
// SOLVEREIGN BFF - Tenant Status Endpoint
// =============================================================================
// GET /api/tenant/status
//
// Returns operational status for tenant/site (healthy/degraded/blocked).
// Blocked status disables write operations in the UI.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { tenantFetch, type TenantStatus } from '@/lib/tenant-api';

// =============================================================================
// MOCK DATA (Replace with actual backend call)
// =============================================================================

const MOCK_STATUS: Record<string, TenantStatus> = {
  // Healthy status
  'lts-transport:HH-NORD': {
    tenant_code: 'lts-transport',
    site_code: 'HH-NORD',
    overall_status: 'healthy',
    is_write_blocked: false,
    reason_code: null,
    reason_message: null,
    escalation_id: null,
    blocked_since: null,
  },
  // Degraded status example
  'lts-transport:MUC-WEST': {
    tenant_code: 'lts-transport',
    site_code: 'MUC-WEST',
    overall_status: 'degraded',
    is_write_blocked: false,
    reason_code: 'SOLVER_SLOW',
    reason_message: 'Solver-Antwortzeiten erhoet (>30s)',
    escalation_id: 'esc-002',
    blocked_since: null,
  },
  // Default: healthy
  'default': {
    tenant_code: 'unknown',
    site_code: 'unknown',
    overall_status: 'healthy',
    is_write_blocked: false,
    reason_code: null,
    reason_message: null,
    escalation_id: null,
    blocked_since: null,
  },
};

// =============================================================================
// HANDLER
// =============================================================================

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const tenantCode = searchParams.get('tenant') || 'unknown';
  const siteCode = searchParams.get('site') || 'unknown';

  // In production: Call backend via tenantFetch
  // const response = await tenantFetch<TenantStatus>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/status`,
  //   { tenantCode, siteCode }
  // );
  // if (response.error) {
  //   return NextResponse.json(response.error, { status: response.status });
  // }
  // return NextResponse.json(response.data);

  // Mock implementation
  const key = `${tenantCode}:${siteCode}`;
  const status = MOCK_STATUS[key] || {
    ...MOCK_STATUS['default'],
    tenant_code: tenantCode,
    site_code: siteCode,
  };

  return NextResponse.json(status);
}
