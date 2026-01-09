// =============================================================================
// SOLVEREIGN BFF - Teams Daily Publish (2-Person HARD GATE)
// =============================================================================
// POST /api/tenant/teams/daily/[importId]/publish - Publish team assignments
//
// HARD GATE: Publish is BLOCKED if:
// - MISMATCH_UNDER: Team has 1 person but stop requires 2 (insufficient staffing)
// - MISMATCH_OVER: Team has 2 persons but no stop requires 2 (resource waste)
//
// Both are equally blocking violations per governance rules.
// Creates immutable snapshot and binds to scenario for solver input.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

interface TwoPersonViolation {
  team_code: string;
  violation_type: 'MISMATCH_UNDER' | 'MISMATCH_OVER';
  team_size: number;
  required_size: number;
  affected_stops: string[];
}

interface PublishResponse {
  import_id: string;
  publish_id: string;
  status: 'PUBLISHED';
  published_at: string;
  published_by: string;
  snapshot_hash: string;
  scenario_binding_id: string | null;
}

interface PublishBlockedResponse {
  code: 'TWO_PERSON_GATE_FAILED';
  message: string;
  violations: TwoPersonViolation[];
  under_count: number;
  over_count: number;
}

// Simulated 2-person compliance check (in production: from backend)
async function checkTwoPersonCompliance(importId: string): Promise<{
  passed: boolean;
  violations: TwoPersonViolation[];
}> {
  // In production: Query backend for actual compliance state
  // This is a mock that returns clean state
  // To test blocking, change violations array

  const violations: TwoPersonViolation[] = [];

  // Example violations for testing (comment out for happy path):
  // violations.push({
  //   team_code: 'TEAM-X01',
  //   violation_type: 'MISMATCH_UNDER',
  //   team_size: 1,
  //   required_size: 2,
  //   affected_stops: ['stop-heavy-001', 'stop-heavy-002'],
  // });
  // violations.push({
  //   team_code: 'TEAM-X02',
  //   violation_type: 'MISMATCH_OVER',
  //   team_size: 2,
  //   required_size: 1,
  //   affected_stops: ['stop-light-003'],
  // });

  return {
    passed: violations.length === 0,
    violations,
  };
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ importId: string }> }
) {
  const { importId } = await params;

  // ==========================================================================
  // RBAC CHECK: publish:teams (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('publish:teams');
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

  // =========================================================================
  // 2-PERSON HARD GATE CHECK
  // =========================================================================
  // Both UNDER and OVER are blocking violations!
  // - UNDER = Safety risk (heavy goods with single driver)
  // - OVER = Resource waste (2 drivers for light goods)
  // =========================================================================

  const complianceResult = await checkTwoPersonCompliance(importId);

  if (!complianceResult.passed) {
    const underViolations = complianceResult.violations.filter(
      v => v.violation_type === 'MISMATCH_UNDER'
    );
    const overViolations = complianceResult.violations.filter(
      v => v.violation_type === 'MISMATCH_OVER'
    );

    const blockedResponse: PublishBlockedResponse = {
      code: 'TWO_PERSON_GATE_FAILED',
      message: `Publish BLOCKED: ${underViolations.length} UNDER violations, ${overViolations.length} OVER violations. Both must be resolved before publish.`,
      violations: complianceResult.violations,
      under_count: underViolations.length,
      over_count: overViolations.length,
    };

    // Return 409 Conflict - the request is valid but violates business rules
    return NextResponse.json(blockedResponse, { status: 409 });
  }

  // =========================================================================
  // PUBLISH (2-Person Gate Passed)
  // =========================================================================

  // In production: Call backend to create immutable snapshot
  // const response = await tenantFetch<PublishResponse>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/${importId}/publish`,
  //   {
  //     tenantCode,
  //     siteCode,
  //     method: 'POST',
  //     idempotencyKey,
  //   }
  // );

  // Mock: Create publish record
  const publishResponse: PublishResponse = {
    import_id: importId,
    publish_id: `pub-${Date.now()}`,
    status: 'PUBLISHED',
    published_at: new Date().toISOString(),
    published_by: userEmail,
    snapshot_hash: `sha256:${Buffer.from(importId + Date.now()).toString('hex').slice(0, 64)}`,
    scenario_binding_id: null, // Will be set when scenario is created
  };

  return NextResponse.json(publishResponse, { status: 201 });
}
