/**
 * BFF Route: Audit Log Viewer API
 *
 * Proxies requests to /api/v1/audit on the backend
 */

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('__Host-sv_platform_session') || cookieStore.get('sv_platform_session');

  if (!sessionCookie) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const limit = searchParams.get('limit') || '50';
  const offset = searchParams.get('offset') || '0';
  const event_type = searchParams.get('event_type');
  const from_date = searchParams.get('from_date');
  const to_date = searchParams.get('to_date');
  const user_email = searchParams.get('user_email');

  let url = `${BACKEND_URL}/api/v1/audit?limit=${limit}&offset=${offset}`;
  if (event_type) url += `&event_type=${encodeURIComponent(event_type)}`;
  if (from_date) url += `&from_date=${encodeURIComponent(from_date)}`;
  if (to_date) url += `&to_date=${encodeURIComponent(to_date)}`;
  if (user_email) url += `&user_email=${encodeURIComponent(user_email)}`;

  try {
    const response = await fetch(url, {
      headers: {
        Cookie: `${sessionCookie.name}=${sessionCookie.value}`,
      },
      cache: 'no-store',
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Failed to fetch audit log:', error);
    return NextResponse.json(
      { success: false, error: 'Backend connection failed' },
      { status: 502 }
    );
  }
}
