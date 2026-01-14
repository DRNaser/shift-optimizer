/**
 * SOLVEREIGN - Platform Admin Permissions BFF Route
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
 * GET /api/platform-admin/permissions
 * List all permissions (optionally filtered by category)
 */
export async function GET(request: NextRequest) {
  const traceId = `permissions-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const category = searchParams.get('category');
  const queryString = category ? `?category=${category}` : '';

  const result = await proxyToBackend(`/api/platform/permissions${queryString}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
