/**
 * SOLVEREIGN - Roster Violations BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Returns: violations[] with BLOCK/WARN severity
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
 * GET /api/roster/plans/[id]/violations
 * Get plan violations filtered by severity/type
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-violations-${id}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const severity = searchParams.get('severity');
  const type = searchParams.get('type');

  const queryParams = new URLSearchParams();
  if (severity) queryParams.set('severity', severity);
  if (type) queryParams.set('type', type);
  const queryString = queryParams.toString();

  const result = await proxyToBackend(
    `/api/v1/roster/plans/${id}/violations${queryString ? `?${queryString}` : ''}`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}
