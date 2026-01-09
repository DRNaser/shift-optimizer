// =============================================================================
// SOLVEREIGN BFF - Validate Import
// =============================================================================
// POST /api/tenant/imports/[importId]/validate
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
  // RBAC CHECK: validate:import (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('validate:import');
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
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports/${importId}/validate`,
  //   { tenantCode, siteCode, method: 'POST' }
  // );

  // Mock: Return validated status
  const validatedImport: StopImportJob = {
    id: importId,
    tenant_code: tenantCode,
    site_code: siteCode,
    filename: 'imported_file.csv',
    status: 'VALIDATED',
    total_rows: 250,
    valid_rows: 248,
    invalid_rows: 2,
    validation_errors: [
      { row: 45, field: 'geocode', error_code: 'MISSING_COORDS', message: 'Keine Koordinaten' },
    ],
    created_at: new Date(Date.now() - 60000).toISOString(),
    validated_at: new Date().toISOString(),
    accepted_at: null,
  };

  return NextResponse.json(validatedImport);
}
