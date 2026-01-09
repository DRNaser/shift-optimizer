// =============================================================================
// SOLVEREIGN BFF - Resolve Escalation API
// =============================================================================
// SECURITY: Requires platform admin auth + CSRF + idempotency.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { statusApi } from '@/lib/platform-api';
import { requirePlatformWriteAccess, getPlatformResolvedBy } from '@/lib/platform-rbac';

/**
 * POST /api/platform/escalations/resolve
 * Resolve an active escalation.
 * SECURITY: Requires platform_admin role + CSRF token + idempotency key.
 */
export async function POST(request: NextRequest) {
  // Write operations require platform admin + CSRF + idempotency
  const denied = await requirePlatformWriteAccess('platform:resolve:escalation', request);
  if (denied) return denied;

  try {
    const body = await request.json();

    // Validate required fields
    if (!body.scope_type || !body.reason_code || !body.resolved_by) {
      return NextResponse.json(
        { error: { code: 'VALIDATION_ERROR', message: 'scope_type, reason_code, and resolved_by are required' } },
        { status: 400 }
      );
    }

    const result = await statusApi.resolveEscalation(body);

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
