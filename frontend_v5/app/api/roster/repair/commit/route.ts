/**
 * SOLVEREIGN - Repair Commit BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Creates a new plan version with the repaired assignments.
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
 * POST /api/roster/repair/commit
 * Commit repair changes (requires idempotency key)
 */
export async function POST(request: NextRequest) {
  const traceId = `repair-commit-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const idempotencyKey = request.headers.get('x-idempotency-key');
  if (!idempotencyKey) {
    return NextResponse.json(
      {
        error_code: 'IDEMPOTENCY_KEY_REQUIRED',
        message: 'x-idempotency-key header is required for commit operations',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  let body: Record<string, unknown>;
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

  // Validate required fields
  if (!body.base_plan_version_id) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'base_plan_version_id is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  if (!body.absences || !Array.isArray(body.absences) || body.absences.length === 0) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'At least one absence is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  const result = await proxyToBackend('/api/v1/roster/repair/commit', session, {
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
