/**
 * BFF Route: Lock Plan (Thin Proxy)
 *
 * POST /api/roster/plans/{id}/lock - Lock a plan (irreversible, arbeitsrechtlich)
 * GET /api/roster/plans/{id}/lock - Get lock status
 *
 * Uses shared proxy helper for consistent error handling + trace_id.
 */
import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

interface RouteParams {
  params: Promise<{ id: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-lock-status-${id}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend(`/api/v1/roster/plans/${id}/lock`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const traceId = `plan-lock-${id}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  let body: Record<string, unknown>;
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

  // Require explicit confirmation for irreversible operation
  if (body.confirm !== true) {
    return NextResponse.json(
      {
        error_code: 'CONFIRMATION_REQUIRED',
        message: 'Lock operation requires explicit confirmation (confirm: true)',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  const result = await proxyToBackend(`/api/v1/roster/plans/${id}/lock`, session, {
    method: 'POST',
    body: { reason: body.reason || 'Locked via Matrix UI' },
    traceId,
  });

  return proxyResultToResponse(result);
}
