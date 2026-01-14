/**
 * SOLVEREIGN - Platform Admin Roles BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 */

import { NextRequest } from 'next/server';
import { simpleProxy } from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

/**
 * GET /api/platform-admin/roles
 * List all roles
 */
export async function GET(request: NextRequest) {
  return simpleProxy(request, '/api/platform/roles', {
    traceId: `roles-list-${Date.now()}`,
  });
}
