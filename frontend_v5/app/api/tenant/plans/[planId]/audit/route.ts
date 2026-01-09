// =============================================================================
// SOLVEREIGN BFF - Plan Audit Endpoint
// =============================================================================
// GET /api/tenant/plans/[planId]/audit - Get audit results
// POST /api/tenant/plans/[planId]/audit - Run audit
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import type { AuditResult } from '@/lib/tenant-api';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

// Mock audit results
const MOCK_AUDITS: Record<string, AuditResult[]> = {
  'plan-001': [
    { check_name: 'Coverage', status: 'PASS', violation_count: 0, details: { assigned: 248, total: 250, unassigned: 2 } },
    { check_name: 'TimeWindow', status: 'PASS', violation_count: 0, details: { on_time_percentage: 96.8 } },
    { check_name: 'ShiftFeasibility', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'SkillsCompliance', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'Overlap', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'TwoPersonMatch', status: 'PASS', violation_count: 0, details: { two_person_stops: 45, matched: 45 } },
  ],
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<AuditResult[]>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/audit`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const audits = MOCK_AUDITS[planId] || [];
  const allPassed = audits.every(a => a.status === 'PASS' || a.status === 'WARN');

  return NextResponse.json({
    plan_id: planId,
    all_passed: allPassed,
    checks_run: audits.length,
    checks_passed: audits.filter(a => a.status === 'PASS').length,
    checks_warn: audits.filter(a => a.status === 'WARN').length,
    checks_fail: audits.filter(a => a.status === 'FAIL').length,
    results: audits,
  });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;

  // ==========================================================================
  // RBAC CHECK: audit:plan (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('audit:plan');
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

  // In production: Call backend to run audit
  // const response = await tenantFetch<AuditResult[]>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/audit`,
  //   { tenantCode, siteCode, method: 'POST' }
  // );

  // Mock: Return same audits but "newly run"
  const audits = MOCK_AUDITS[planId] || [
    { check_name: 'Coverage', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'TimeWindow', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'ShiftFeasibility', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'SkillsCompliance', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'Overlap', status: 'PASS', violation_count: 0, details: {} },
    { check_name: 'TwoPersonMatch', status: 'PASS', violation_count: 0, details: {} },
  ];

  const allPassed = audits.every(a => a.status === 'PASS' || a.status === 'WARN');

  return NextResponse.json({
    plan_id: planId,
    all_passed: allPassed,
    checks_run: audits.length,
    checks_passed: audits.filter(a => a.status === 'PASS').length,
    checks_warn: audits.filter(a => a.status === 'WARN').length,
    checks_fail: audits.filter(a => a.status === 'FAIL').length,
    results: audits,
  });
}
