// =============================================================================
// SOLVEREIGN BFF - Tenant Detail API
// =============================================================================
// SECURITY: All routes require platform auth. Writes need CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { tenantsApi } from '@/lib/platform-api';
import { requirePlatformPermission, requirePlatformWriteAccess } from '@/lib/platform-rbac';

interface RouteParams {
  params: Promise<{ tenantCode: string }>;
}

/**
 * GET /api/platform/tenants/[tenantCode]
 * Get tenant details.
 * SECURITY: Requires platform viewer or admin.
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const denied = await requirePlatformPermission('platform:read:tenants');
  if (denied) return denied;

  const { tenantCode } = await params;
  const result = await tenantsApi.get(tenantCode);

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}

/**
 * PATCH /api/platform/tenants/[tenantCode]
 * Update tenant.
 * SECURITY: Requires platform_admin + CSRF + idempotency.
 */
export async function PATCH(request: NextRequest, { params }: RouteParams) {
  const denied = await requirePlatformWriteAccess('platform:update:tenant', request);
  if (denied) return denied;

  const { tenantCode } = await params;

  try {
    const body = await request.json();
    const result = await tenantsApi.update(tenantCode, body);

    if (result.error) {
      return NextResponse.json(
        { error: result.error },
        { status: result.status }
      );
    }

    return NextResponse.json(result.data);
  } catch {
    return NextResponse.json(
      { error: { code: 'INVALID_JSON', message: 'Invalid request body' } },
      { status: 400 }
    );
  }
}
