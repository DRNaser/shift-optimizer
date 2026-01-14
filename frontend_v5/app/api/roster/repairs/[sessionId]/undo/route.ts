/**
 * BFF Route: Repair Undo (Thin Proxy)
 *
 * POST /api/roster/repairs/[sessionId]/undo - Undo last repair action (idempotent)
 *
 * CANONICAL: Backend owns undo logic and idempotency.
 * 1-step undo to reduce dispatcher anxiety during pilot.
 *
 * Backend endpoint: POST /api/v1/roster/repairs/{sessionId}/undo
 *
 * Error codes from backend:
 * - NOTHING_TO_UNDO (400): No applied actions to undo
 * - SNAPSHOT_ALREADY_PUBLISHED (409): Plan was published after session start
 * - PLAN_LOCKED_NO_UNDO (409): Plan is locked
 * - SESSION_EXPIRED (410): Session has expired
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

export async function POST(request: NextRequest, context: RouteContext) {
  const { sessionId } = await context.params;
  const traceId = `repair-undo-${sessionId}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Forward idempotency key (prevents double-undo)
  const idempotencyKey = request.headers.get('x-idempotency-key');
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['x-idempotency-key'] = idempotencyKey;
  }

  const result = await proxyToBackend(`/api/v1/roster/repairs/${sessionId}/undo`, session, {
    method: 'POST',
    headers,
    traceId,
  });

  return proxyResultToResponse(result);
}
