/**
 * SOLVEREIGN - Platform Admin Tenant Detail BFF Route
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
 * GET /api/platform-admin/tenants/[tenantId]
 * Get tenant details
 */
export async function GET(request: NextRequest, context: RouteContext) {
  const { tenantId } = await context.params;
  const traceId = `tenant-detail-${tenantId}-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend(`/api/platform/tenants/${tenantId}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
