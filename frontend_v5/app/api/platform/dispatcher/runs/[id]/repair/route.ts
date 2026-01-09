// =============================================================================
// SOLVEREIGN BFF - Dispatcher Repair Request
// =============================================================================
// POST /api/platform/dispatcher/runs/[id]/repair
//
// Submits a repair request for sick-call/no-show.
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
    driver_id: string;
    driver_name: string;
    absence_type: 'sick' | 'vacation' | 'no_show';
    affected_tours: string[];
    urgency?: 'critical' | 'high' | 'normal';
    notes?: string;
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
  if (!body.driver_id || !body.driver_name || !body.absence_type || !body.affected_tours) {
    return NextResponse.json(
      { error: 'MISSING_FIELDS', message: 'driver_id, driver_name, absence_type, and affected_tours are required' },
      { status: 400 }
    );
  }

  if (!Array.isArray(body.affected_tours) || body.affected_tours.length === 0) {
    return NextResponse.json(
      { error: 'INVALID_TOURS', message: 'affected_tours must be a non-empty array' },
      { status: 400 }
    );
  }

  // Call backend
  const response = await dispatcherApi.requestRepair(tenantCode, siteCode, runId, {
    driver_id: body.driver_id,
    driver_name: body.driver_name,
    absence_type: body.absence_type,
    affected_tours: body.affected_tours,
    urgency: body.urgency,
    notes: body.notes,
  });

  if (response.error) {
    return NextResponse.json(
      { error: response.error.code, message: response.error.message },
      { status: response.status }
    );
  }

  return NextResponse.json(response.data);
}
