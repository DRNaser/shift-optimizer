// =============================================================================
// SOLVEREIGN BFF - Teams Daily Validate
// =============================================================================
// POST /api/tenant/teams/daily/[importId]/validate - Validate team import
//
// Runs validation checks:
// - Team structure (team_code, driver assignments)
// - 2-Person compliance pre-check
// - Shift time validity
// - Vehicle assignments
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

interface ValidationError {
  row: number;
  field: string;
  error_code: string;
  message: string;
  severity: 'ERROR' | 'WARNING';
}

interface TwoPersonCheck {
  team_code: string;
  demand_status: 'MATCHED' | 'MISMATCH_UNDER' | 'MISMATCH_OVER';
  team_size: number;
  required_size: number;
  stop_ids: string[];
}

interface ValidationResponse {
  import_id: string;
  status: 'VALIDATED' | 'FAILED';
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  errors: ValidationError[];
  warnings: ValidationError[];
  two_person_checks: TwoPersonCheck[];
  can_publish: boolean;
  blocking_reasons: string[];
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ importId: string }> }
) {
  const { importId } = await params;

  // ==========================================================================
  // RBAC CHECK: validate:teams (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('validate:teams');
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

  // In production: Call backend
  // const response = await tenantFetch<ValidationResponse>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/${importId}/validate`,
  //   { tenantCode, siteCode, method: 'POST', idempotencyKey }
  // );

  // Mock validation with 2-person checks
  // Simulate finding one MISMATCH_UNDER and one MISMATCH_OVER
  const twoPersonChecks: TwoPersonCheck[] = [
    {
      team_code: 'TEAM-A01',
      demand_status: 'MATCHED',
      team_size: 2,
      required_size: 2,
      stop_ids: ['stop-001', 'stop-002'],
    },
    {
      team_code: 'TEAM-A02',
      demand_status: 'MATCHED',
      team_size: 1,
      required_size: 1,
      stop_ids: ['stop-003'],
    },
  ];

  // Check for blocking violations
  const blockingReasons: string[] = [];
  const underViolations = twoPersonChecks.filter(c => c.demand_status === 'MISMATCH_UNDER');
  const overViolations = twoPersonChecks.filter(c => c.demand_status === 'MISMATCH_OVER');

  if (underViolations.length > 0) {
    blockingReasons.push(
      `${underViolations.length} Team(s) mit zu wenig Fahrern fuer 2-Person Stops: ${underViolations.map(v => v.team_code).join(', ')}`
    );
  }

  if (overViolations.length > 0) {
    blockingReasons.push(
      `${overViolations.length} Team(s) mit 2 Fahrern aber ohne 2-Person Demand: ${overViolations.map(v => v.team_code).join(', ')}`
    );
  }

  const canPublish = blockingReasons.length === 0;

  const validationResponse: ValidationResponse = {
    import_id: importId,
    status: 'VALIDATED',
    total_rows: 10,
    valid_rows: 10,
    invalid_rows: 0,
    errors: [],
    warnings: [],
    two_person_checks: twoPersonChecks,
    can_publish: canPublish,
    blocking_reasons: blockingReasons,
  };

  return NextResponse.json(validationResponse);
}
