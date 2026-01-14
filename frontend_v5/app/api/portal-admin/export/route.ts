/**
 * SOLVEREIGN - Portal Admin Export BFF Route
 *
 * Exports driver list as CSV.
 * Note: This route streams CSV directly, can't use standard proxy.
 * RBAC: portal.export.read permission required.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getSessionCookie, unauthorizedResponse } from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

/**
 * GET /api/portal-admin/export
 * Export driver list as CSV
 */
export async function GET(request: NextRequest) {
  const traceId = `portal-export-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = request.nextUrl;
  const snapshotId = searchParams.get('snapshot_id');
  const filter = searchParams.get('filter') || 'ALL';

  if (!snapshotId) {
    return NextResponse.json(
      {
        error_code: 'VALIDATION_ERROR',
        message: 'snapshot_id is required',
        trace_id: traceId,
      },
      { status: 400 }
    );
  }

  try {
    const url = new URL(`${BACKEND_URL}/api/v1/portal/dashboard/export`);
    url.searchParams.set('snapshot_id', snapshotId);
    url.searchParams.set('filter', filter);
    url.searchParams.set('format', 'csv');

    const response = await fetch(url.toString(), {
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/csv',
        Cookie: `${session.name}=${session.value}`,
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        {
          error_code: 'BACKEND_ERROR',
          message: (data as { detail?: string }).detail || `Backend error: ${response.status}`,
          trace_id: traceId,
        },
        { status: response.status }
      );
    }

    const csv = await response.text();

    return new NextResponse(csv, {
      status: 200,
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="portal-export-${snapshotId.slice(0, 8)}.csv"`,
        'Cache-Control': 'no-store',
        Vary: 'Cookie',
      },
    });
  } catch (error) {
    console.error('[BFF] Portal export error:', error);
    return NextResponse.json(
      {
        error_code: 'BFF_ERROR',
        message: 'Internal server error',
        trace_id: traceId,
      },
      { status: 500 }
    );
  }
}
