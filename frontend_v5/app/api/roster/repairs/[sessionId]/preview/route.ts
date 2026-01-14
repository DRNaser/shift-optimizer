/**
 * BFF Route: Repair Preview (Thin Proxy)
 *
 * POST /api/roster/repairs/[sessionId]/preview - Preview repair action
 *
 * CANONICAL: Backend computes preview with pin/violation checks.
 * Backend endpoint: POST /api/v1/roster/repairs/{sessionId}/preview
 */
import { NextRequest } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

interface RouteContext {
  params: Promise<{ sessionId: string }>;
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { sessionId } = await context.params;
  const traceId = `repair-preview-${sessionId}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  // Parse body for forwarding
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    // Let backend handle validation
  }

  const result = await proxyToBackend(`/api/v1/roster/repairs/${sessionId}/preview`, session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}
