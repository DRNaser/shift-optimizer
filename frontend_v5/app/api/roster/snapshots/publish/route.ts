/**
 * BFF Route: Publish Snapshot (Thin Proxy)
 *
 * POST /api/roster/snapshots/publish - Publish a plan snapshot
 *
 * Uses shared proxy helper for consistent error handling + trace_id.
 * Requires x-idempotency-key header.
 */
import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export async function POST(request: NextRequest) {
  const traceId = `snapshot-publish-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Require idempotency key
  const idempotencyKey = request.headers.get('x-idempotency-key');
  if (!idempotencyKey) {
    return NextResponse.json(
      {
        error_code: 'IDEMPOTENCY_KEY_REQUIRED',
        message: 'x-idempotency-key header is required for publish',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        error_code: 'INVALID_JSON',
        message: 'Request body must be valid JSON',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  const result = await proxyToBackend('/api/v1/roster/snapshots/publish', session, {
    method: 'POST',
    body,
    headers: { 'x-idempotency-key': idempotencyKey },
    traceId,
  });

  return proxyResultToResponse(result);
}
