// =============================================================================
// SOLVEREIGN BFF - Tenant Entitlement Detail API
// =============================================================================
// SECURITY: Requires platform admin + CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { tenantsApi } from '@/lib/platform-api';
import { requirePlatformWriteAccess } from '@/lib/platform-rbac';

interface RouteParams {
  params: Promise<{ tenantCode: string; packId: string }>;
}

/**
 * PUT /api/platform/tenants/[tenantCode]/entitlements/[packId]
 * Update entitlement (enable/disable pack, update config).
 * SECURITY: Requires platform_admin + CSRF + idempotency.
 */
export async function PUT(request: NextRequest, { params }: RouteParams) {
  const denied = await requirePlatformWriteAccess('platform:update:entitlement', request);
  if (denied) return denied;

  const { tenantCode, packId } = await params;

  try {
    const body = await request.json();

    // Validate required fields
    if (typeof body.is_enabled !== 'boolean') {
      return NextResponse.json(
        { error: { code: 'VALIDATION_ERROR', message: 'is_enabled (boolean) is required' } },
        { status: 400 }
      );
    }

    const result = await tenantsApi.setEntitlement(tenantCode, packId, body);

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
