/**
 * SOLVEREIGN - Portal Admin Summary BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * RBAC: portal.summary.read permission required.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

/**
 * GET /api/portal-admin/summary
 * Get dashboard summary for a snapshot
 */
export async function GET(request: NextRequest) {
  const traceId = `portal-summary-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const snapshotId = request.nextUrl.searchParams.get('snapshot_id');
  if (!snapshotId) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'snapshot_id is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  const result = await proxyToBackend(
    `/api/v1/portal/dashboard/summary?snapshot_id=${snapshotId}`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}
