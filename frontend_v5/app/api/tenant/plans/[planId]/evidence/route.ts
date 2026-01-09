// =============================================================================
// SOLVEREIGN BFF - Evidence Pack Endpoint
// =============================================================================
// GET /api/tenant/plans/[planId]/evidence - Get evidence pack
// POST /api/tenant/plans/[planId]/evidence - Generate evidence pack
//
// Evidence pack includes:
// - Plan snapshot (routes, assignments)
// - Audit results
// - Input hash + output hash
// - SHA256 for integrity verification
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import type { EvidencePack } from '@/lib/tenant-api';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

// Mock evidence packs
const MOCK_EVIDENCE: Record<string, EvidencePack> = {
  'plan-001': {
    id: 'evd-001',
    plan_id: 'plan-001',
    artifact_url: '/api/tenant/plans/plan-001/evidence/download',
    sha256_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    created_at: '2026-01-06T08:00:00Z',
    size_bytes: 245678,
  },
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<EvidencePack>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/evidence`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const evidence = MOCK_EVIDENCE[planId];
  if (!evidence) {
    return NextResponse.json(
      { code: 'NOT_FOUND', message: 'Evidence pack not found. Generate one first.' },
      { status: 404 }
    );
  }

  return NextResponse.json(evidence);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;

  // ==========================================================================
  // RBAC CHECK: generate:evidence (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('generate:evidence');
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

  // In production: Call backend to generate evidence
  // const response = await tenantFetch<EvidencePack>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/evidence`,
  //   { tenantCode, siteCode, method: 'POST' }
  // );

  // Mock: Create evidence pack
  const evidence: EvidencePack = {
    id: `evd-${Date.now()}`,
    plan_id: planId,
    artifact_url: `/api/tenant/plans/${planId}/evidence/download`,
    sha256_hash: `sha256-${Date.now()}`,
    created_at: new Date().toISOString(),
    size_bytes: Math.floor(Math.random() * 500000) + 100000,
  };

  return NextResponse.json(evidence, { status: 201 });
}
