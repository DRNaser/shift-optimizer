// =============================================================================
// SOLVEREIGN BFF - Dispatcher Runs List
// =============================================================================
// GET /api/platform/dispatcher/runs
//
// Lists runs for the current tenant/site.
// Requires session auth + tenant context.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { dispatcherApi } from '@/lib/platform-api';
import { cookies } from 'next/headers';

export async function GET(request: NextRequest) {
  // Get tenant/site from query params or session
  const searchParams = request.nextUrl.searchParams;
  const tenantCode = searchParams.get('tenant') || 'lts';
  const siteCode = searchParams.get('site') || 'wien';
  const limit = parseInt(searchParams.get('limit') || '20', 10);
  const statusFilter = searchParams.get('status') || undefined;

  // Verify session (simplified for MVP - in production use real session validation)
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('sv_session');

  if (!sessionCookie) {
    return NextResponse.json(
      { error: 'UNAUTHORIZED', message: 'Session required' },
      { status: 401 }
    );
  }

  // Call backend via platform API
  const response = await dispatcherApi.listRuns(tenantCode, siteCode, limit, statusFilter);

  if (response.error) {
    return NextResponse.json(
      { error: response.error.code, message: response.error.message },
      { status: response.status }
    );
  }

  return NextResponse.json(response.data);
}
