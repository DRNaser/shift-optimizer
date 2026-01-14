/**
 * SOLVEREIGN - Portal Admin Details BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * RBAC: portal.details.read permission required.
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
 * GET /api/portal-admin/details
 * Get driver list for a snapshot
 */
export async function GET(request: NextRequest) {
  const traceId = `portal-details-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = request.nextUrl;
  const snapshotId = searchParams.get('snapshot_id');
  const filter = searchParams.get('filter') || 'ALL';
  const page = searchParams.get('page') || '1';
  const pageSize = searchParams.get('page_size') || '50';

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

  const params = new URLSearchParams();
  params.set('snapshot_id', snapshotId);
  params.set('filter', filter);
  params.set('page', page);
  params.set('page_size', pageSize);

  const result = await proxyToBackend(
    `/api/v1/portal/dashboard/details?${params.toString()}`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}
