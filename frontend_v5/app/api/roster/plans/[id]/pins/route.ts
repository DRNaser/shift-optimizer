/**
 * SOLVEREIGN - Roster Pins BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Supports: GET (list), POST (add), DELETE (remove)
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

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * GET /api/roster/plans/[id]/pins
 * List pins for a plan
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-pins-list-${id}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const includeInactive = searchParams.get('include_inactive') === 'true';

  const result = await proxyToBackend(
    `/api/v1/roster/plans/${id}/pins${includeInactive ? '?include_inactive=true' : ''}`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}

/**
 * POST /api/roster/plans/[id]/pins
 * Add a pin (requires idempotency key)
 */
export async function POST(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-pins-add-${id}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const idempotencyKey = request.headers.get('x-idempotency-key');
  if (!idempotencyKey) {
    return NextResponse.json(
      {
        error_code: 'IDEMPOTENCY_KEY_REQUIRED',
        message: 'x-idempotency-key header is required',
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

  const result = await proxyToBackend(`/api/v1/roster/plans/${id}/pins`, session, {
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

/**
 * DELETE /api/roster/plans/[id]/pins?pin_id=X
 * Remove a pin
 */
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-pins-remove-${id}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const pinId = searchParams.get('pin_id');

  if (!pinId) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'pin_id query parameter is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const result = await proxyToBackend(`/api/v1/roster/plans/${id}/pins/${pinId}`, session, {
    method: 'DELETE',
    body,
    headers: {
      Origin: request.headers.get('origin') || 'http://localhost:3000',
    },
    traceId,
  });

  return proxyResultToResponse(result);
}
