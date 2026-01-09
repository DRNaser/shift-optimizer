// =============================================================================
// SOLVEREIGN BFF - Accept Import
// =============================================================================
// POST /api/tenant/imports/[importId]/accept
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import type { StopImportJob } from '@/lib/tenant-api';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ importId: string }> }
) {
  const { importId } = await params;

  // ==========================================================================
  // RBAC CHECK: accept:import (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('accept:import');
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
  // const response = await tenantFetch<StopImportJob>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports/${importId}/accept`,
  //   { tenantCode, siteCode, method: 'POST' }
  // );

  // Mock: Return accepted status
  const acceptedImport: StopImportJob = {
    id: importId,
    tenant_code: tenantCode,
    site_code: siteCode,
    filename: 'imported_file.csv',
    status: 'ACCEPTED',
    total_rows: 250,
    valid_rows: 250,
    invalid_rows: 0,
    validation_errors: [],
    created_at: new Date(Date.now() - 120000).toISOString(),
    validated_at: new Date(Date.now() - 60000).toISOString(),
    accepted_at: new Date().toISOString(),
  };

  return NextResponse.json(acceptedImport);
}
