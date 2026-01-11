/**
 * BFF Route: Roster Plans API
 *
 * Proxies requests to /api/v1/roster/plans on the backend
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
  const status_filter = searchParams.get('status');

  let url = `${BACKEND_URL}/api/v1/roster/plans?limit=${limit}&offset=${offset}`;
  if (status_filter) {
    url += `&status_filter=${status_filter}`;
  }

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
    console.error('Failed to fetch plans:', error);
    return NextResponse.json(
      { success: false, error: 'Backend connection failed' },
      { status: 502 }
    );
  }
}

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('__Host-sv_platform_session') || cookieStore.get('sv_platform_session');

  if (!sessionCookie) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const body = await request.json();
  const idempotencyKey = request.headers.get('x-idempotency-key');

  if (!idempotencyKey) {
    return NextResponse.json(
      { success: false, error: 'x-idempotency-key header required' },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/roster/plans`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `${sessionCookie.name}=${sessionCookie.value}`,
        'x-idempotency-key': idempotencyKey,
        Origin: request.headers.get('origin') || 'http://localhost:3000',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Failed to create plan:', error);
    return NextResponse.json(
      { success: false, error: 'Backend connection failed' },
      { status: 502 }
    );
  }
}
