// =============================================================================
// SOLVEREIGN BFF - Organizations API
// =============================================================================
// Proxies to FastAPI with HMAC signature for platform admin operations.
// SECURITY: All write operations require platform admin auth + CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { organizationsApi, type Organization } from '@/lib/platform-api';
import { requirePlatformPermission, requirePlatformWriteAccess } from '@/lib/platform-rbac';

/**
 * GET /api/platform/orgs
 * List all organizations with aggregated status.
 */
export async function GET() {
  // Read operations require platform viewer or admin
  const denied = await requirePlatformPermission('platform:read:orgs');
  if (denied) return denied;

  const result = await organizationsApi.list();

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}

/**
 * POST /api/platform/orgs
 * Create a new organization.
 * SECURITY: Requires platform_admin role + CSRF token + idempotency key.
 */
export async function POST(request: NextRequest) {
  // Write operations require platform admin + CSRF + idempotency
  const denied = await requirePlatformWriteAccess('platform:create:org', request);
  if (denied) return denied;

  try {
    const body = await request.json();

    // Validate required fields
    if (!body.org_code || !body.name) {
      return NextResponse.json(
        { error: { code: 'VALIDATION_ERROR', message: 'org_code and name are required' } },
        { status: 400 }
      );
    }

    const result = await organizationsApi.create(body);

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
