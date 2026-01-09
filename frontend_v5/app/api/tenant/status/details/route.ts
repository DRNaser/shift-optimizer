// =============================================================================
// SOLVEREIGN BFF - Tenant Status Details
// =============================================================================
// GET /api/tenant/status/details - Full status with escalations and history
//
// Response includes:
// - Current operational status
// - Active escalations (S0/S1/S2/S3)
// - Status history (last 30 days)
// - Degraded service details
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

interface StatusHistoryEntry {
  id: string;
  timestamp: string;
  old_status: 'healthy' | 'degraded' | 'blocked';
  new_status: 'healthy' | 'degraded' | 'blocked';
  reason: string;
  changed_by: string | null;
}

interface Escalation {
  id: string;
  tenant_id: string;
  site_id: string | null;
  severity: 'S0' | 'S1' | 'S2' | 'S3';
  category: string;
  title: string;
  description: string;
  status: 'OPEN' | 'ACKNOWLEDGED' | 'IN_PROGRESS' | 'RESOLVED';
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
}

interface DegradedService {
  service: string;
  status: 'degraded' | 'unavailable';
  message: string;
  estimated_recovery: string | null;
}

interface StatusDetails {
  tenant_code: string;
  site_code: string;
  current_status: 'healthy' | 'degraded' | 'blocked';
  is_write_blocked: boolean;
  blocked_reason: string | null;
  degraded_services: DegradedService[];
  active_escalations: Escalation[];
  status_history: StatusHistoryEntry[];
  last_health_check: string;
}

async function getTenantContext() {
  const cookieStore = await cookies();
  const tenantCode = cookieStore.get('sv_tenant_code')?.value || 'lts-transport';
  const siteCode = cookieStore.get('sv_current_site')?.value || 'wien';
  return { tenantCode, siteCode };
}

// Mock status details
function getMockStatusDetails(tenantCode: string, siteCode: string): StatusDetails {
  return {
    tenant_code: tenantCode,
    site_code: siteCode,
    current_status: 'healthy',
    is_write_blocked: false,
    blocked_reason: null,
    degraded_services: [],
    active_escalations: [
      {
        id: 'esc-001',
        tenant_id: tenantCode,
        site_id: siteCode,
        severity: 'S3',
        category: 'PERFORMANCE',
        title: 'Solver response time elevated',
        description: 'Solver response times are 20% above baseline. Monitoring closely.',
        status: 'ACKNOWLEDGED',
        created_at: '2026-01-06T08:00:00Z',
        acknowledged_at: '2026-01-06T08:15:00Z',
        acknowledged_by: 'ops@solvereign.com',
        resolved_at: null,
        resolved_by: null,
        resolution_note: null,
      },
    ],
    status_history: [
      {
        id: 'hist-001',
        timestamp: '2026-01-05T14:00:00Z',
        old_status: 'degraded',
        new_status: 'healthy',
        reason: 'Database maintenance completed successfully',
        changed_by: 'system',
      },
      {
        id: 'hist-002',
        timestamp: '2026-01-05T12:00:00Z',
        old_status: 'healthy',
        new_status: 'degraded',
        reason: 'Scheduled database maintenance',
        changed_by: 'ops@solvereign.com',
      },
    ],
    last_health_check: new Date().toISOString(),
  };
}

export async function GET(request: NextRequest) {
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<StatusDetails>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/status/details`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const details = getMockStatusDetails(tenantCode, siteCode);
  return NextResponse.json(details);
}
