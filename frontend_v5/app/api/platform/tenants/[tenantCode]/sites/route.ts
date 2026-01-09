// =============================================================================
// SOLVEREIGN BFF - Tenant Sites API
// =============================================================================
// SECURITY: All write operations require platform admin auth + CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { tenantsApi } from '@/lib/platform-api';
import { requirePlatformPermission, requirePlatformWriteAccess } from '@/lib/platform-rbac';

interface RouteParams {
  params: Promise<{ tenantCode: string }>;
}

/**
 * GET /api/platform/tenants/[tenantCode]/sites
 * List sites for a tenant.
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  // Read operations require platform viewer or admin
  const denied = await requirePlatformPermission('platform:read:sites');
  if (denied) return denied;

  const { tenantCode } = await params;
  const result = await tenantsApi.getSites(tenantCode);

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}

/**
 * POST /api/platform/tenants/[tenantCode]/sites
 * Create a new site under tenant.
 * SECURITY: Requires platform_admin role + CSRF token + idempotency key.
 */
export async function POST(request: NextRequest, { params }: RouteParams) {
  // Write operations require platform admin + CSRF + idempotency
  const denied = await requirePlatformWriteAccess('platform:create:site', request);
  if (denied) return denied;

  const { tenantCode } = await params;

  try {
    const body = await request.json();

    // Validate required fields
    if (!body.site_code || !body.name || !body.timezone) {
      return NextResponse.json(
        { error: { code: 'VALIDATION_ERROR', message: 'site_code, name, and timezone are required' } },
        { status: 400 }
      );
    }

    const result = await tenantsApi.createSite(tenantCode, body);

    if (result.error) {
      return NextResponse.json(
        { error: result.error },
        { status: result.status }
      );
    }

    return NextResponse.json(result.data, { status: 201 });
  } catch {
    return NextResponse.json(
      { error: { code: 'INVALID_JSON', message: 'Invalid request body' } },
      { status: 400 }
    );
  }
}
