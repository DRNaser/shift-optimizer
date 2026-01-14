/**
 * SOLVEREIGN - Platform Admin Sessions BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 */

import { NextRequest } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

/**
 * GET /api/platform-admin/sessions
 * List active sessions (optionally filtered by user_id or tenant_id)
 */
export async function GET(request: NextRequest) {
  const traceId = `sessions-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const userId = searchParams.get('user_id');
  const tenantId = searchParams.get('tenant_id');
  const activeOnly = searchParams.get('active_only') ?? 'true';

  const params = new URLSearchParams();
  if (userId) params.set('user_id', userId);
  if (tenantId) params.set('tenant_id', tenantId);
  params.set('active_only', activeOnly);

  const result = await proxyToBackend(`/api/platform/sessions?${params.toString()}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}

/**
 * POST /api/platform-admin/sessions
 * Revoke sessions
 */
export async function POST(request: NextRequest) {
  const traceId = `sessions-revoke-${Date.now()}`;

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

  const result = await proxyToBackend('/api/platform/sessions/revoke', session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}
