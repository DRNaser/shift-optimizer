/**
 * SOLVEREIGN - Portal Admin Snapshots BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * RBAC: portal.summary.read permission required.
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
 * GET /api/portal-admin/snapshots
 * List available snapshots
 */
export async function GET(request: NextRequest) {
  const traceId = `portal-snapshots-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend('/api/v1/portal/dashboard/snapshots', session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
