/**
 * SOLVEREIGN - Roster Snapshots BFF Route
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
 * GET /api/roster/snapshots
 * List snapshots with optional filtering
 */
export async function GET(request: NextRequest) {
  const traceId = `snapshots-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const limit = searchParams.get('limit') || '50';
  const offset = searchParams.get('offset') || '0';
  const statusFilter = searchParams.get('status');

  const params = new URLSearchParams();
  params.set('limit', limit);
  params.set('offset', offset);
  if (statusFilter) {
    params.set('status_filter', statusFilter);
  }

  const result = await proxyToBackend(`/api/v1/roster/snapshots?${params.toString()}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
