/**
 * SOLVEREIGN - Audit Log Viewer BFF Route
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
 * GET /api/audit
 * List audit log entries with filtering
 */
export async function GET(request: NextRequest) {
  const traceId = `audit-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const params = new URLSearchParams();

  params.set('limit', searchParams.get('limit') || '50');
  params.set('offset', searchParams.get('offset') || '0');

  const eventType = searchParams.get('event_type');
  const fromDate = searchParams.get('from_date');
  const toDate = searchParams.get('to_date');
  const userEmail = searchParams.get('user_email');

  if (eventType) params.set('event_type', eventType);
  if (fromDate) params.set('from_date', fromDate);
  if (toDate) params.set('to_date', toDate);
  if (userEmail) params.set('user_email', userEmail);

  const result = await proxyToBackend(`/api/v1/audit?${params.toString()}`, session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
