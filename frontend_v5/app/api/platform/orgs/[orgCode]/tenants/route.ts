// =============================================================================
// SOLVEREIGN BFF - Organization Tenants API
// =============================================================================
// SECURITY: All write operations require platform admin auth + CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { organizationsApi } from '@/lib/platform-api';
import { requirePlatformPermission, requirePlatformWriteAccess } from '@/lib/platform-rbac';

interface RouteParams {
  params: Promise<{ orgCode: string }>;
}

/**
 * GET /api/platform/orgs/[orgCode]/tenants
 * List tenants for an organization.
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  // Read operations require platform viewer or admin
  const denied = await requirePlatformPermission('platform:read:tenants');
  if (denied) return denied;

  const { orgCode } = await params;
  const result = await organizationsApi.getTenants(orgCode);

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}

/**
 * POST /api/platform/orgs/[orgCode]/tenants
 * Create a new tenant under organization.
 * SECURITY: Requires platform_admin role + CSRF token + idempotency key.
 */
export async function POST(request: NextRequest, { params }: RouteParams) {
  // Write operations require platform admin + CSRF + idempotency
  const denied = await requirePlatformWriteAccess('platform:create:tenant', request);
  if (denied) return denied;

  const { orgCode } = await params;

  try {
    const body = await request.json();

    // Validate required fields
    if (!body.tenant_code || !body.name) {
      return NextResponse.json(
        { error: { code: 'VALIDATION_ERROR', message: 'tenant_code and name are required' } },
        { status: 400 }
      );
    }

    const result = await organizationsApi.createTenant(orgCode, body);

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
