/**
 * BFF Route: Repair Preview API
 *
 * Proxies requests to /api/v1/roster/repair/preview on the backend.
 * Read-only endpoint that previews repair changes.
 */

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie =
    cookieStore.get('__Host-sv_platform_session') ||
    cookieStore.get('sv_platform_session');

  if (!sessionCookie) {
    return NextResponse.json(
      { success: false, error: 'Unauthorized' },
      { status: 401 }
    );
  }

  const body = await request.json();

  // Validate required fields
  if (!body.base_plan_version_id) {
    return NextResponse.json(
      { success: false, error: 'base_plan_version_id is required' },
      { status: 400 }
    );
  }

  if (!body.absences || !Array.isArray(body.absences) || body.absences.length === 0) {
    return NextResponse.json(
      { success: false, error: 'At least one absence is required' },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/roster/repair/preview`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `${sessionCookie.name}=${sessionCookie.value}`,
        Origin: request.headers.get('origin') || 'http://localhost:3000',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('[BFF] Failed to preview repair:', error);
    return NextResponse.json(
      { success: false, error: 'Backend connection failed' },
      { status: 502 }
    );
  }
}
