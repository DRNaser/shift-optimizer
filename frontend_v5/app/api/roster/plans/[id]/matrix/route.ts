/**
 * SOLVEREIGN - Roster Matrix BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Returns: drivers[], days[], cells[] with severity badges
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
 * GET /api/roster/plans/[id]/matrix
 * Get plan matrix view
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-matrix-${id}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend(`/api/v1/roster/plans/${id}/matrix`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
