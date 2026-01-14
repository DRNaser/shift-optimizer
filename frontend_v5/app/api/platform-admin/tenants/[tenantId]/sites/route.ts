/**
 * SOLVEREIGN - Platform Admin Sites BFF Route
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

interface RouteContext {
  params: Promise<{ tenantId: string }>;
}

/**
 * GET /api/platform-admin/tenants/[tenantId]/sites
 * List sites for a tenant
 */
export async function GET(request: NextRequest, context: RouteContext) {
  const { tenantId } = await context.params;
  const traceId = `sites-list-${tenantId}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend(`/api/platform/tenants/${tenantId}/sites`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}

/**
 * POST /api/platform-admin/tenants/[tenantId]/sites
 * Create a new site
 */
export async function POST(request: NextRequest, context: RouteContext) {
  const { tenantId } = await context.params;
  const traceId = `sites-create-${tenantId}-${Date.now()}`;

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

  const result = await proxyToBackend(`/api/platform/tenants/${tenantId}/sites`, session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}
