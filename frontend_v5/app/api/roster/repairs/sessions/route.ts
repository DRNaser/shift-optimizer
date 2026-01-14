/**
 * BFF Route: Repair Sessions (Thin Proxy)
 *
 * POST /api/roster/repairs/sessions - Create session
 *
 * CANONICAL: Backend owns session lifecycle.
 * BFF is thin proxy only - no local session creation.
 *
 * Backend endpoint: POST /api/v1/roster/repairs/sessions
 */
import { NextRequest } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export async function POST(request: NextRequest) {
  const traceId = `repair-session-create-${Date.now()}`;

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

  // Forward idempotency key
  const idempotencyKey = request.headers.get('x-idempotency-key');
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['x-idempotency-key'] = idempotencyKey;
  }

  // Proxy to backend canonical endpoint
  const result = await proxyToBackend('/api/v1/roster/repairs/sessions', session, {
    method: 'POST',
    body,
    headers,
    traceId,
  });

  return proxyResultToResponse(result);
}
