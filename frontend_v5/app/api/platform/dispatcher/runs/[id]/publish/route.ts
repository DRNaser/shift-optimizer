// =============================================================================
// SOLVEREIGN BFF - Dispatcher Publish Run
// =============================================================================
// POST /api/platform/dispatcher/runs/[id]/publish
//
// Publishes a run with approval.
// Gates enforced:
// - Site enablement (Wien only)
// - Kill switch
// - Human approval with role validation
// - Evidence hash linkage
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { dispatcherApi } from '@/lib/platform-api';
import { cookies } from 'next/headers';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: runId } = await params;

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

  // Parse request body
  let body: {
    approver_id: string;
    approver_role: 'dispatcher' | 'ops_lead' | 'platform_admin';
    reason: string;
    override_warn?: boolean;
  };

  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: 'INVALID_BODY', message: 'Invalid JSON body' },
      { status: 400 }
    );
  }

  // Validate required fields
  if (!body.approver_id || !body.approver_role || !body.reason) {
    return NextResponse.json(
      { error: 'MISSING_FIELDS', message: 'approver_id, approver_role, and reason are required' },
      { status: 400 }
    );
  }

  if (body.reason.length < 10) {
    return NextResponse.json(
      { error: 'INVALID_REASON', message: 'Reason must be at least 10 characters' },
      { status: 400 }
    );
  }

  // Call backend
  const response = await dispatcherApi.publishRun(tenantCode, siteCode, runId, {
    approver_id: body.approver_id,
    approver_role: body.approver_role,
    reason: body.reason,
    override_warn: body.override_warn,
  });

  if (response.error) {
    return NextResponse.json(
      { error: response.error.code, message: response.error.message, details: response.error.details },
      { status: response.status }
    );
  }

  return NextResponse.json(response.data);
}
