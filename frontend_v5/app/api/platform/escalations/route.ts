// =============================================================================
// SOLVEREIGN BFF - Escalations API
// =============================================================================
// SECURITY: All write operations require platform admin auth + CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { statusApi } from '@/lib/platform-api';
import { requirePlatformPermission, requirePlatformWriteAccess } from '@/lib/platform-rbac';

/**
 * GET /api/platform/escalations
 * List escalations, optionally filtered by scope.
 */
export async function GET(request: NextRequest) {
  // Read operations require platform viewer or admin
  const denied = await requirePlatformPermission('platform:read:escalations');
  if (denied) return denied;

  const { searchParams } = new URL(request.url);
  const scopeType = searchParams.get('scope_type') || undefined;
  const scopeId = searchParams.get('scope_id') || undefined;

  const result = await statusApi.getEscalations(scopeType, scopeId);

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}

/**
 * POST /api/platform/escalations
 * Record a new escalation.
 * SECURITY: Requires platform_admin role + CSRF token + idempotency key.
 */
export async function POST(request: NextRequest) {
  // Write operations require platform admin + CSRF + idempotency
  const denied = await requirePlatformWriteAccess('platform:create:escalation', request);
  if (denied) return denied;

  try {
    const body = await request.json();

    // Validate required fields
    if (!body.scope_type || !body.reason_code) {
      return NextResponse.json(
        { error: { code: 'VALIDATION_ERROR', message: 'scope_type and reason_code are required' } },
        { status: 400 }
      );
    }

    const result = await statusApi.recordEscalation(body);

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
