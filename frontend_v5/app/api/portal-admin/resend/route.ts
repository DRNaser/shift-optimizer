/**
 * SOLVEREIGN - Portal Admin Resend BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * RBAC: portal.resend.write permission required.
 * Additional: portal.approve.write for DECLINED/SKIPPED filters.
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
 * POST /api/portal-admin/resend
 * Resend notifications to drivers
 */
export async function POST(request: NextRequest) {
  const traceId = `portal-resend-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
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
  if (!body.snapshot_id) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'snapshot_id is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  // Validate guardrails for DECLINED filter
  if (body.filter === 'DECLINED') {
    if (!body.include_declined) {
      return NextResponse.json(
        {
          error_code: 'VALIDATION_ERROR',
          message: 'include_declined=true required for DECLINED filter',
          trace_id: traceId,
        },
        { status: 400 }
      );
    }
    if (!body.declined_reason || String(body.declined_reason).length < 10) {
      return NextResponse.json(
        {
          error_code: 'VALIDATION_ERROR',
          message: 'declined_reason (min 10 chars) required for DECLINED filter',
          trace_id: traceId,
        },
        { status: 400 }
      );
    }
  }

  // Validate guardrails for SKIPPED filter
  if (body.filter === 'SKIPPED') {
    if (!body.include_skipped) {
      return NextResponse.json(
        {
          error_code: 'VALIDATION_ERROR',
          message: 'include_skipped=true required for SKIPPED filter',
          trace_id: traceId,
        },
        { status: 400 }
      );
    }
    if (!body.skipped_reason || String(body.skipped_reason).length < 10) {
      return NextResponse.json(
        {
          error_code: 'VALIDATION_ERROR',
          message: 'skipped_reason (min 10 chars) required for SKIPPED filter',
          trace_id: traceId,
        },
        { status: 400 }
      );
    }
  }

  const result = await proxyToBackend('/api/v1/portal/dashboard/resend', session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}
