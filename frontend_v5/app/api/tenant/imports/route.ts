// =============================================================================
// SOLVEREIGN BFF - Tenant Imports Endpoint
// =============================================================================
// GET /api/tenant/imports - List imports
// POST /api/tenant/imports - Upload new import
//
// Uses HMAC V2 signing for backend communication.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import {
  tenantFetch,
  generateTenantIdempotencyKey,
  type StopImportJob,
} from '@/lib/tenant-api';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

// =============================================================================
// MOCK DATA
// =============================================================================

const MOCK_IMPORTS: StopImportJob[] = [
  {
    id: 'imp-001',
    tenant_code: 'lts-transport',
    site_code: 'wien',
    filename: 'fls_export_2026-01-06.csv',
    status: 'VALIDATED',
    total_rows: 250,
    valid_rows: 248,
    invalid_rows: 2,
    validation_errors: [
      { row: 45, field: 'geocode', error_code: 'MISSING_COORDS', message: 'Keine Koordinaten' },
      { row: 128, field: 'time_window', error_code: 'INVALID_FORMAT', message: 'Ungültiges Zeitformat' },
    ],
    created_at: '2026-01-06T08:30:00Z',
    validated_at: '2026-01-06T08:31:15Z',
    accepted_at: null,
  },
  {
    id: 'imp-002',
    tenant_code: 'lts-transport',
    site_code: 'wien',
    filename: 'fls_export_2026-01-05.csv',
    status: 'ACCEPTED',
    total_rows: 235,
    valid_rows: 235,
    invalid_rows: 0,
    validation_errors: [],
    created_at: '2026-01-05T07:45:00Z',
    validated_at: '2026-01-05T07:46:30Z',
    accepted_at: '2026-01-05T08:00:00Z',
  },
];

// =============================================================================
// HANDLERS
// =============================================================================

export async function GET(request: NextRequest) {
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<StopImportJob[]>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports`,
  //   { tenantCode, siteCode }
  // );
  // if (response.error) {
  //   return NextResponse.json(response.error, { status: response.status });
  // }
  // return NextResponse.json(response.data);

  // Mock
  const imports = MOCK_IMPORTS.filter(
    i => i.tenant_code === tenantCode && i.site_code === siteCode
  );
  return NextResponse.json(imports);
}

export async function POST(request: NextRequest) {
  // ==========================================================================
  // RBAC CHECK: upload:stops (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('upload:stops');
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
    const { filename, content } = body;

    if (!filename || !content) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'filename and content required' },
        { status: 400 }
      );
    }

    // In production: Call backend with idempotency key
    // const response = await tenantFetch<StopImportJob>(
    //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports`,
    //   {
    //     tenantCode,
    //     siteCode,
    //     method: 'POST',
    //     body: { filename, content },
    //     idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'upload-import', filename),
    //   }
    // );
    // if (response.error) {
    //   return NextResponse.json(response.error, { status: response.status });
    // }
    // return NextResponse.json(response.data, { status: 201 });

    // Mock: Create new import
    const newImport: StopImportJob = {
      id: `imp-${Date.now()}`,
      tenant_code: tenantCode,
      site_code: siteCode,
      filename,
      status: 'PENDING',
      total_rows: 0,
      valid_rows: 0,
      invalid_rows: 0,
      validation_errors: [],
      created_at: new Date().toISOString(),
      validated_at: null,
      accepted_at: null,
    };

    return NextResponse.json(newImport, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { code: 'PARSE_ERROR', message: 'Invalid JSON body' },
      { status: 400 }
    );
  }
}
