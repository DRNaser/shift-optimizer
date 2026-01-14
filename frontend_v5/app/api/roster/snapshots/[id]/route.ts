/**
 * SOLVEREIGN - Roster Snapshot Detail BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
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
 * GET /api/roster/snapshots/[id]
 * Get snapshot details
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `snapshot-detail-${id}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend(`/api/v1/roster/snapshots/${id}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
