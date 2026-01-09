// =============================================================================
// SOLVEREIGN BFF - Tenant Entitlements API
// =============================================================================
// SECURITY: Requires platform auth.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { tenantsApi } from '@/lib/platform-api';
import { requirePlatformPermission } from '@/lib/platform-rbac';

interface RouteParams {
  params: Promise<{ tenantCode: string }>;
}

/**
 * GET /api/platform/tenants/[tenantCode]/entitlements
 * List entitlements (pack enablements) for a tenant.
 * SECURITY: Requires platform viewer or admin.
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const denied = await requirePlatformPermission('platform:read:entitlements');
  if (denied) return denied;

  const { tenantCode } = await params;
  const result = await tenantsApi.getEntitlements(tenantCode);

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}
