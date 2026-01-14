/**
 * BFF Route: Repair Apply (Thin Proxy)
 *
 * POST /api/roster/repairs/{sessionId}/apply - Apply repair changes
 *
 * CANONICAL: Backend owns session lifecycle, expiry enforcement, and idempotency.
 * BFF is thin proxy only.
 *
 * Backend endpoint: POST /api/v1/roster/repairs/{sessionId}/apply
 *
 * Error codes from backend:
 * - SESSION_EXPIRED (410): Session has expired
 * - SESSION_NOT_OPEN (409): Session is not OPEN
 * - PLAN_LOCKED (409): Plan is locked
 * - PIN_CONFLICTS (409): Pin conflicts prevent apply
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
  const traceId = `repair-apply-${sessionId}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Parse body for forwarding
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    // No body - let backend handle validation
  }

  // Forward idempotency key (required by backend for apply)
  const idempotencyKey = request.headers.get('x-idempotency-key');
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['x-idempotency-key'] = idempotencyKey;
  }

  const result = await proxyToBackend(`/api/v1/roster/repairs/${sessionId}/apply`, session, {
    method: 'POST',
    body,
    headers,
    traceId,
  });

  return proxyResultToResponse(result);
}
