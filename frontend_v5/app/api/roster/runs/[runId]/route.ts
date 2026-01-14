/**
 * SOLVEREIGN - Roster Run Detail BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Includes status transformation for frontend compatibility.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

interface RouteContext {
  params: Promise<{ runId: string }>;
}

// Status transformation (backend → frontend)
const STATUS_MAP: Record<string, string> = {
  'PENDING': 'QUEUED',
  'RUNNING': 'RUNNING',
  'SUCCESS': 'COMPLETED',
  'FAILED': 'FAILED',
};

/**
 * GET /api/roster/runs/[runId]
 * Get run status
 */
export async function GET(request: NextRequest, context: RouteContext) {
  const { runId } = await context.params;
  const traceId = `run-detail-${runId}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Note: Path is doubled due to FastAPI router prefix stacking
  const result = await proxyToBackend(
    `/api/v1/roster/api/v1/roster/runs/${runId}`,
    session,
    { method: 'GET', traceId }
  );

  // Transform status if needed
  if (result.ok && typeof result.data === 'object' && result.data !== null) {
    const data = result.data as Record<string, unknown>;
    if (data.status && typeof data.status === 'string' && STATUS_MAP[data.status]) {
      data.status = STATUS_MAP[data.status];
    }

    const response = NextResponse.json(data, { status: result.status });
    response.headers.set('Cache-Control', 'no-store');
    response.headers.set('Vary', 'Cookie');
    return response;
  }

  // Error case - use standard proxy response
  const response = NextResponse.json(result.data, { status: result.status });
  response.headers.set('Cache-Control', 'no-store');
  response.headers.set('Vary', 'Cookie');
  return response;
}
