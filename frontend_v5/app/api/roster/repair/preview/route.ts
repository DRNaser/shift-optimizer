/**
 * BFF Route: Repair Preview API
 *
 * Proxies requests to /api/v1/roster/repair/preview on the backend.
 * Read-only endpoint that previews repair changes.
 *
 * Uses shared proxy helper for consistent error handling.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export async function POST(request: NextRequest) {
  const traceId = `repair-preview-${Date.now()}`;

  // Auth check using centralized cookie extraction
  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Parse and validate request body
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

  // Validate required fields
  const data = body as Record<string, unknown>;
  if (!data.base_plan_version_id) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'base_plan_version_id is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  if (!data.absences || !Array.isArray(data.absences) || data.absences.length === 0) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'At least one absence is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  // Forward idempotency key if present
  const idempotencyKey = request.headers.get('x-idempotency-key');
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['x-idempotency-key'] = idempotencyKey;
  }

  // Proxy to backend using shared helper
  const result = await proxyToBackend('/api/v1/roster/repair/preview', session, {
    method: 'POST',
    body,
    headers,
    traceId,
  });

  return proxyResultToResponse(result);
}
