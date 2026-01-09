// =============================================================================
// SOLVEREIGN BFF - Dispatcher System Status
// =============================================================================
// GET /api/platform/dispatcher/status
//
// Gets current system status including:
// - Kill switch state
// - Publish/lock enablement
// - Latest run
// - Pending repairs
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { dispatcherApi } from '@/lib/platform-api';
import { cookies } from 'next/headers';

export async function GET(request: NextRequest) {
  // Get tenant/site from query params
  const searchParams = request.nextUrl.searchParams;
  const tenantCode = searchParams.get('tenant') || 'lts';
  const siteCode = searchParams.get('site') || 'wien';

  // Verify session
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('sv_session');

  if (!sessionCookie) {
    return NextResponse.json(
      { error: 'UNAUTHORIZED', message: 'Session required' },
      { status: 401 }
    );
  }

  // Call backend
  const response = await dispatcherApi.getStatus(tenantCode, siteCode);

  if (response.error) {
    return NextResponse.json(
      { error: response.error.code, message: response.error.message },
      { status: response.status }
    );
  }

  return NextResponse.json(response.data);
}
