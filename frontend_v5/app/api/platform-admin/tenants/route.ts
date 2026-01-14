/**
 * SOLVEREIGN - Platform Admin Tenants BFF Route
 *
 * Uses centralized proxy.ts for:
 * - Cookie extraction (priority chain)
 * - Error normalization ({ error_code, message, trace_id })
 * - Cache-Control headers
 * - trace_id propagation
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
 * GET /api/platform-admin/tenants
 * List all tenants (platform admin only)
 */
export async function GET(request: NextRequest) {
  const traceId = `tenants-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Forward query params
  const { searchParams } = new URL(request.url);
  const includeCounts = searchParams.get('include_counts') || 'false';

  const result = await proxyToBackend(
    `/api/platform/tenants?include_counts=${includeCounts}`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}

/**
 * POST /api/platform-admin/tenants
 * Create a new tenant (platform admin only)
 */
export async function POST(request: NextRequest) {
  const traceId = `tenants-create-${Date.now()}`;

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

  const result = await proxyToBackend('/api/platform/tenants', session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}
