/**
 * SOLVEREIGN - Roster Diff BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Returns: KPI deltas, assignment changes, publish gating info
 */

import { NextRequest } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * GET /api/roster/plans/[id]/diff
 * Get diff between current plan and base snapshot
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-diff-${id}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const baseSnapshotId = searchParams.get('base_snapshot_id');

  const queryParams = new URLSearchParams();
  if (baseSnapshotId) queryParams.set('base_snapshot_id', baseSnapshotId);
  const queryString = queryParams.toString();

  const result = await proxyToBackend(
    `/api/v1/roster/plans/${id}/diff${queryString ? `?${queryString}` : ''}`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}
