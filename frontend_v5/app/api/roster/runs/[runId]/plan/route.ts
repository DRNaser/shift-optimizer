/**
 * SOLVEREIGN - Roster Run Plan/Result BFF Route
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

interface RouteContext {
  params: Promise<{ runId: string }>;
}

/**
 * GET /api/roster/runs/[runId]/plan
 * Get run result/plan (schedule)
 */
export async function GET(request: NextRequest, context: RouteContext) {
  const { runId } = await context.params;
  const traceId = `run-plan-${runId}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Note: Path is doubled due to FastAPI router prefix stacking
  const result = await proxyToBackend(
    `/api/v1/roster/api/v1/roster/runs/${runId}/schedule`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}
