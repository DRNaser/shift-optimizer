/**
 * BFF Route: Repair Session Status (Thin Proxy)
 *
 * GET /api/roster/repairs/[sessionId] - Get session status
 *
 * CANONICAL: Backend owns session lifecycle.
 * Backend endpoint: GET /api/v1/roster/repairs/{sessionId}
 */
import { NextRequest } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

interface RouteContext {
  params: Promise<{ sessionId: string }>;
}

export async function GET(request: NextRequest, context: RouteContext) {
  const { sessionId } = await context.params;
  const traceId = `repair-session-status-${sessionId}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend(`/api/v1/roster/repairs/${sessionId}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
