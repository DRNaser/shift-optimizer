/**
 * Repair Orchestrator Prepare BFF Route
 * ======================================
 *
 * POST /api/roster/repairs/orchestrated/prepare
 *
 * Create a repair draft from a chosen proposal.
 * Requires x-idempotency-key header for safe retries.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export async function POST(request: NextRequest) {
  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse();
  }

  // Extract idempotency key (required)
  const idempotencyKey = request.headers.get('x-idempotency-key');
  if (!idempotencyKey) {
    return NextResponse.json(
      {
        error_code: 'IDEMPOTENCY_KEY_REQUIRED',
        message: 'x-idempotency-key header is required for prepare',
        trace_id: `bff-${Date.now()}`,
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
        error_code: 'INVALID_BODY',
        message: 'Request body must be valid JSON',
        trace_id: `bff-${Date.now()}`,
      },
      { status: 400 }
    );
  }

  const result = await proxyToBackend(
    '/api/v1/roster/repairs/orchestrated/prepare',
    session,
    {
      method: 'POST',
      body,
      headers: {
        'x-idempotency-key': idempotencyKey,
      },
    }
  );

  return proxyResultToResponse(result);
}
