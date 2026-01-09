// =============================================================================
// SOLVEREIGN BFF - Tenant Import Detail Endpoint
// =============================================================================
// GET /api/tenant/imports/[importId] - Get import details
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import type { StopImportJob } from '@/lib/tenant-api';

async function getTenantContext() {
  const cookieStore = await cookies();
  const tenantCode = cookieStore.get('sv_tenant_code')?.value || 'lts-transport';
  const siteCode = cookieStore.get('sv_current_site')?.value || 'wien';
  return { tenantCode, siteCode };
}

// Mock data lookup
const MOCK_IMPORTS: Record<string, StopImportJob> = {
  'imp-001': {
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
      { row: 128, field: 'time_window', error_code: 'INVALID_FORMAT', message: 'Ungueltiges Zeitformat' },
    ],
    created_at: '2026-01-06T08:30:00Z',
    validated_at: '2026-01-06T08:31:15Z',
    accepted_at: null,
  },
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ importId: string }> }
) {
  const { importId } = await params;
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<StopImportJob>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports/${importId}`,
  //   { tenantCode, siteCode }
  // );

  // Mock
  const importJob = MOCK_IMPORTS[importId];
  if (!importJob) {
    return NextResponse.json(
      { code: 'NOT_FOUND', message: 'Import not found' },
      { status: 404 }
    );
  }

  return NextResponse.json(importJob);
}
