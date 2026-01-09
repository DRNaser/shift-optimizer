// =============================================================================
// SOLVEREIGN BFF - Organization Detail API
// =============================================================================
// SECURITY: All routes require platform auth. Writes need CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { organizationsApi } from '@/lib/platform-api';
import { requirePlatformPermission, requirePlatformWriteAccess } from '@/lib/platform-rbac';

interface RouteParams {
  params: Promise<{ orgCode: string }>;
}

/**
 * GET /api/platform/orgs/[orgCode]
 * Get organization details.
 * SECURITY: Requires platform viewer or admin.
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const denied = await requirePlatformPermission('platform:read:orgs');
  if (denied) return denied;

  const { orgCode } = await params;
  const result = await organizationsApi.get(orgCode);

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}

/**
 * PATCH /api/platform/orgs/[orgCode]
 * Update organization.
 * SECURITY: Requires platform_admin + CSRF + idempotency.
 */
export async function PATCH(request: NextRequest, { params }: RouteParams) {
  const denied = await requirePlatformWriteAccess('platform:update:org', request);
  if (denied) return denied;

  const { orgCode } = await params;

  try {
    const body = await request.json();
    const result = await organizationsApi.update(orgCode, body);

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
