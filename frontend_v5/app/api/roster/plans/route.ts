/**
 * SOLVEREIGN - Roster Plans BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

/**
 * GET /api/roster/plans
 * List plans with optional filtering
 */
export async function GET(request: NextRequest) {
  const traceId = `plans-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const limit = searchParams.get('limit') || '50';
  const offset = searchParams.get('offset') || '0';
  const statusFilter = searchParams.get('status');

  const params = new URLSearchParams();
  params.set('limit', limit);
  params.set('offset', offset);
  if (statusFilter) {
    params.set('status_filter', statusFilter);
  }

  const result = await proxyToBackend(`/api/v1/roster/plans?${params.toString()}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}

/**
 * POST /api/roster/plans
 * Create a new plan (requires idempotency key)
 */
export async function POST(request: NextRequest) {
  const traceId = `plans-create-${Date.now()}`;

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
        message: 'x-idempotency-key header is required for plan creation',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return proxyResultToResponse({
      ok: false,
      status: 400,
      data: { error_code: 'INVALID_JSON', message: 'Request body must be valid JSON' },
      traceId,
      contentType: 'application/json',
    });
  }

  const result = await proxyToBackend('/api/v1/roster/plans', session, {
    method: 'POST',
    body,
    headers: {
      'x-idempotency-key': idempotencyKey,
      Origin: request.headers.get('origin') || 'http://localhost:3000',
    },
    traceId,
  });

  return proxyResultToResponse(result);
}
