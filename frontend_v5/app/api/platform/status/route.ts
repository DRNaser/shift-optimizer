// =============================================================================
// SOLVEREIGN BFF - Platform Status API
// =============================================================================
// SECURITY: Requires platform auth.
// =============================================================================

import { NextResponse } from 'next/server';
import { statusApi } from '@/lib/platform-api';
import { requirePlatformPermission } from '@/lib/platform-rbac';

/**
 * GET /api/platform/status
 * Get overall platform status with aggregated escalations.
 * SECURITY: Requires platform viewer or admin.
 */
export async function GET() {
  const denied = await requirePlatformPermission('platform:read:status');
  if (denied) return denied;

  const result = await statusApi.getPlatformStatus();

  if (result.error) {
    return NextResponse.json(
      { error: result.error },
      { status: result.status }
    );
  }

  return NextResponse.json(result.data);
}
