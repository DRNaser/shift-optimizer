/**
 * SOLVEREIGN - Audit Event Types BFF Route
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
 * GET /api/audit/event-types
 * List available event types
 */
export async function GET(request: NextRequest) {
  const traceId = `audit-event-types-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend('/api/v1/audit/event-types', session, {
    method: 'GET',
    traceId,
  });

  return proxyResultToResponse(result);
}
