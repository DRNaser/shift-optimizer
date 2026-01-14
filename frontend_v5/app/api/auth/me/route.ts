/**
 * BFF Route: Auth Me (Thin Proxy)
 *
 * GET /api/auth/me - Returns current authenticated user info
 *
 * Uses shared proxy helper for consistent error handling + trace_id.
 */
import { NextRequest, NextResponse } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET(request: NextRequest) {
  const traceId = `auth-me-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const result = await proxyToBackend('/api/auth/me', session, {
    method: 'GET',
    traceId,
  });

  // Wrap successful response in expected format
  if (result.ok && typeof result.data === 'object' && result.data !== null) {
    const response = NextResponse.json(
      { success: true, user: result.data },
      { status: 200 }
    );
    response.headers.set('Cache-Control', 'no-store, no-cache, must-revalidate');
    return response;
  }

  return proxyResultToResponse(result);
}
