// =============================================================================
// SOLVEREIGN BFF - 2-Person Compliance Check
// =============================================================================
// GET /api/tenant/teams/daily/check-compliance?date=YYYY-MM-DD
//
// HARD GATE: Returns violations that BLOCK scenario publish.
// If any MISMATCH_UNDER violations exist, publish is blocked.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

async function getTenantContext() {
  const cookieStore = await cookies();
  const tenantCode = cookieStore.get('sv_tenant_code')?.value || 'lts-transport';
  const siteCode = cookieStore.get('sv_current_site')?.value || 'wien';
  return { tenantCode, siteCode };
}

interface ComplianceViolation {
  stop_id: string;
  stop_order_id: string;
  team_id: string;
  team_code: string;
  violation_type: 'MISMATCH_UNDER' | 'MISMATCH_OVER';
  reason: string;
  severity: 'BLOCK' | 'WARN';
}

interface ComplianceCheckResult {
  date: string;
  compliant: boolean;
  can_publish: boolean;
  violations: ComplianceViolation[];
  summary: {
    total_stops_checked: number;
    two_person_required: number;
    two_person_assigned: number;
    blocking_violations: number;
    warning_violations: number;
  };
}

// =============================================================================
// HANDLER
// =============================================================================

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const date = searchParams.get('date') || new Date().toISOString().split('T')[0];
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<ComplianceCheckResult>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/check-two-person?date=${date}`,
  //   { tenantCode, siteCode }
  // );

  // Mock: Simulate compliance check
  const violations: ComplianceViolation[] = [
    {
      stop_id: 'stop-045',
      stop_order_id: 'ORD-2026-001234',
      team_id: 'team-003',
      team_code: 'T-003',
      violation_type: 'MISMATCH_UNDER',
      reason: 'Stop erfordert 2-Mann Team (Montage), aber Team T-003 hat nur 1 Fahrer',
      severity: 'BLOCK',
    },
  ];

  const blockingViolations = violations.filter(v => v.severity === 'BLOCK');
  const warningViolations = violations.filter(v => v.severity === 'WARN');

  const result: ComplianceCheckResult = {
    date,
    compliant: blockingViolations.length === 0,
    can_publish: blockingViolations.length === 0,
    violations,
    summary: {
      total_stops_checked: 250,
      two_person_required: 45,
      two_person_assigned: 44,
      blocking_violations: blockingViolations.length,
      warning_violations: warningViolations.length,
    },
  };

  return NextResponse.json(result);
}
