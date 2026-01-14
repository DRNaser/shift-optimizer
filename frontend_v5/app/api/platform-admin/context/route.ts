/**
 * SOLVEREIGN - Platform Admin Context BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Handles GET/POST/DELETE for platform admin context switching.
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
 * GET /api/platform-admin/context
 * Get current active context
 */
export async function GET() {
  const traceId = `context-get-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend('/api/platform/context', session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}

/**
 * POST /api/platform-admin/context
 * Set active context (tenant_id, site_id)
 */
export async function POST(request: NextRequest) {
  const traceId = `context-set-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
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

  const result = await proxyToBackend('/api/platform/context', session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}

/**
 * DELETE /api/platform-admin/context
 * Clear active context
 */
export async function DELETE() {
  const traceId = `context-clear-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend('/api/platform/context', session, {
    method: 'DELETE',
    traceId,
  });

  // Handle 204 No Content
  if (result.status === 204) {
    return new NextResponse(null, {
      status: 204,
      headers: {
        'Cache-Control': 'no-store',
        'Vary': 'Cookie',
      },
    });
  }

  return proxyResultToResponse(result);
}
