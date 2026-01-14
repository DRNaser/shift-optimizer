/**
 * SOLVEREIGN - Platform Admin Users BFF Route
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
 * GET /api/platform-admin/users
 * List all users (optionally filtered by tenant)
 */
export async function GET(request: NextRequest) {
  const traceId = `users-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const tenantId = searchParams.get('tenant_id');
  const queryString = tenantId ? `?tenant_id=${tenantId}` : '';

  const result = await proxyToBackend(`/api/platform/users${queryString}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}

/**
 * POST /api/platform-admin/users
 * Create a new user with binding
 */
export async function POST(request: NextRequest) {
  const traceId = `users-create-${Date.now()}`;

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

  const result = await proxyToBackend('/api/platform/users', session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}
