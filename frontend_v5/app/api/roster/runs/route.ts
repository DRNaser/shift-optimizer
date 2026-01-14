/**
 * SOLVEREIGN - Roster Runs BFF Route
 *
 * Uses centralized proxy.ts for consistent error handling.
 * Includes day format conversion for backend compatibility.
 */

import { NextRequest } from 'next/server';
import {
  getSessionCookie,
  proxyToBackend,
  proxyResultToResponse,
  unauthorizedResponse,
} from '@/lib/bff/proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

// Day string to integer mapping (backend expects 1=Mon, 7=Sun)
const DAY_TO_INT: Record<string, number> = {
  'Mon': 1, 'MONDAY': 1, 'Monday': 1,
  'Tue': 2, 'TUESDAY': 2, 'Tuesday': 2,
  'Wed': 3, 'WEDNESDAY': 3, 'Wednesday': 3,
  'Thu': 4, 'THURSDAY': 4, 'Thursday': 4,
  'Fri': 5, 'FRIDAY': 5, 'Friday': 5,
  'Sat': 6, 'SATURDAY': 6, 'Saturday': 6,
  'Sun': 7, 'SUNDAY': 7, 'Sunday': 7,
};

function convertDayToInt(day: string | number): number {
  if (typeof day === 'number') return day;
  return DAY_TO_INT[day] || parseInt(day, 10) || 1;
}

/**
 * GET /api/roster/runs
 * List optimization runs
 */
export async function GET(request: NextRequest) {
  const traceId = `runs-list-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  const { searchParams } = new URL(request.url);
  const limit = searchParams.get('limit') || '20';
  const offset = searchParams.get('offset') || '0';

  // Fixed path - was incorrectly doubled before
  const result = await proxyToBackend(
    `/api/v1/roster/runs?limit=${limit}&offset=${offset}`,
    session,
    { method: 'GET', traceId }
  );

  return proxyResultToResponse(result);
}

/**
 * POST /api/roster/runs
 * Create a new optimization run
 */
export async function POST(request: NextRequest) {
  const traceId = `runs-create-${Date.now()}`;

  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(traceId);
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return proxyResultToResponse({
      ok: false,
      status: 400,
      data: { error_code: 'INVALID_JSON', message: 'Request body must be valid JSON' },
      traceId,
      contentType: 'application/json',
    });
  }

  // Convert day strings to integers in tours
  if (body.tours && Array.isArray(body.tours)) {
    body.tours = body.tours.map((tour: { day: string | number; [key: string]: unknown }) => ({
      ...tour,
      day: convertDayToInt(tour.day),
    }));
  }

  // Convert available_days in drivers if present
  if (body.drivers && Array.isArray(body.drivers)) {
    body.drivers = body.drivers.map((driver: { available_days?: (string | number)[]; [key: string]: unknown }) => ({
      ...driver,
      available_days: driver.available_days
        ? driver.available_days.map((d: string | number) => convertDayToInt(d))
        : [1, 2, 3, 4, 5],
    }));
  }

  // Transform frontend schema to backend schema
  // Frontend: { run: { seed, time_budget_seconds, config_overrides } }
  // Backend: { config_overrides: { seed, time_limit_seconds } }
  if (body.run) {
    const runConfig = body.run as Record<string, unknown>;
    body.config_overrides = {
      seed: runConfig.seed ?? 94,
      time_limit_seconds: runConfig.time_budget_seconds ?? 120,
      ...((runConfig.config_overrides as Record<string, unknown>) || {}),
    };
    delete body.run;
  }

  // Map week_start to plan_date
  if (body.week_start && !body.plan_date) {
    body.plan_date = body.week_start;
    delete body.week_start;
  }

  // Fixed path - was incorrectly doubled before
  const result = await proxyToBackend('/api/v1/roster/runs', session, {
    method: 'POST',
    body,
    traceId,
  });

  return proxyResultToResponse(result);
}
