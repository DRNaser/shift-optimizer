/**
 * Repair Orchestrator Preview BFF Route
 * ======================================
 *
 * POST /api/roster/repairs/orchestrated/preview
 *
 * Generate Top-K repair proposals for an incident.
 * This is a read-only operation - no database mutations.
 */

import { NextRequest } from 'next/server';
import { simpleProxy } from '@/lib/bff/proxy';

export async function POST(request: NextRequest) {
  return simpleProxy(request, '/api/v1/roster/repairs/orchestrated/preview');
}
