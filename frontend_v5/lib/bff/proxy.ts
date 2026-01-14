/**
 * BFF Proxy Utilities
 * ===================
 *
 * Shared utilities for BFF routes to ensure consistent behavior:
 * - Cookie extraction (centralized)
 * - Backend proxy with proper error passthrough
 * - trace_id propagation
 *
 * NON-NEGOTIABLES:
 * - Never return {} on errors
 * - Always preserve upstream status code
 * - Always include trace_id in error responses
 * - Forward raw body when not JSON parseable
 */

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || 'http://localhost:8000';

/**
 * Supported cookie names in priority order.
 * Production uses __Host- prefix for security.
 */
const SESSION_COOKIE_NAMES = [
  '__Host-sv_platform_session', // Production (Secure, no Domain)
  'sv_platform_session',        // Development
  'admin_session',              // Legacy fallback
] as const;

export interface SessionCookie {
  name: string;
  value: string;
}

/**
 * Extract session cookie from request.
 * Tries multiple cookie names in priority order.
 *
 * @returns SessionCookie or null if not authenticated
 */
export async function getSessionCookie(): Promise<SessionCookie | null> {
  const cookieStore = await cookies();

  for (const name of SESSION_COOKIE_NAMES) {
    const cookie = cookieStore.get(name);
    if (cookie) {
      return { name, value: cookie.value };
    }
  }

  return null;
}

/**
 * Create unauthorized response with trace_id.
 */
export function unauthorizedResponse(traceId?: string): NextResponse {
  return NextResponse.json(
    {
      error_code: 'UNAUTHORIZED',
      message: 'Authentication required',
      trace_id: traceId || `bff-${Date.now()}`,
    },
    { status: 401 }
  );
}

export interface ProxyOptions {
  /** HTTP method */
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  /** Request body (will be JSON stringified) */
  body?: unknown;
  /** Additional headers */
  headers?: Record<string, string>;
  /** Custom trace_id (auto-generated if not provided) */
  traceId?: string;
  /** Timeout in ms (default 30000) */
  timeout?: number;
}

export interface ProxyResult {
  /** Whether the upstream returned 2xx */
  ok: boolean;
  /** HTTP status code from upstream */
  status: number;
  /** Parsed JSON body or raw text if not JSON */
  data: unknown;
  /** trace_id (from upstream or generated) */
  traceId: string;
  /** Content-Type from upstream */
  contentType: string | null;
}

/**
 * Proxy request to backend with proper error handling.
 *
 * GUARANTEES:
 * - Preserves upstream status code
 * - Preserves upstream body (JSON or raw)
 * - Always includes trace_id
 * - Never swallows error details
 *
 * @param path - Backend API path (e.g., '/api/v1/roster/plans')
 * @param session - Session cookie from getSessionCookie()
 * @param options - Proxy options
 * @returns ProxyResult with upstream response
 */
export async function proxyToBackend(
  path: string,
  session: SessionCookie,
  options: ProxyOptions = {}
): Promise<ProxyResult> {
  const {
    method = 'GET',
    body,
    headers: extraHeaders = {},
    traceId = `bff-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    timeout = 30000,
  } = options;

  const url = `${BACKEND_URL}${path}`;

  const headers: Record<string, string> = {
    Cookie: `${session.name}=${session.value}`,
    'x-trace-id': traceId,
    ...extraHeaders,
  };

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });

    clearTimeout(timeoutId);

    const contentType = response.headers.get('content-type');
    let data: unknown;

    // Try to parse as JSON, fall back to text
    if (contentType?.includes('application/json')) {
      try {
        data = await response.json();
      } catch {
        data = await response.text();
      }
    } else {
      data = await response.text();
    }

    // Extract trace_id from response if present
    const upstreamTraceId =
      (typeof data === 'object' && data !== null && 'trace_id' in data
        ? (data as { trace_id?: string }).trace_id
        : null) || traceId;

    return {
      ok: response.ok,
      status: response.status,
      data,
      traceId: upstreamTraceId,
      contentType,
    };
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof Error && error.name === 'AbortError') {
      return {
        ok: false,
        status: 504,
        data: {
          error_code: 'GATEWAY_TIMEOUT',
          message: `Backend request timed out after ${timeout}ms`,
          trace_id: traceId,
        },
        traceId,
        contentType: 'application/json',
      };
    }

    return {
      ok: false,
      status: 502,
      data: {
        error_code: 'BAD_GATEWAY',
        message: 'Backend connection failed',
        trace_id: traceId,
        details: error instanceof Error ? error.message : String(error),
      },
      traceId,
      contentType: 'application/json',
    };
  }
}

/**
 * Normalize error data to standard envelope format.
 * Handles various backend error formats:
 * - { error_code, message, trace_id } (correct)
 * - { error: { code, message } } (platform-admin style)
 * - { detail: string } (FastAPI)
 * - { detail: { code, message } } (FastAPI structured)
 * - { success: false, error: string } (legacy)
 */
export function normalizeErrorResponse(
  data: unknown,
  traceId: string,
  status: number
): { error_code: string; message: string; trace_id: string; field?: string; details?: unknown } {
  if (!data || typeof data !== 'object') {
    return {
      error_code: 'UNKNOWN_ERROR',
      message: 'An unexpected error occurred',
      trace_id: traceId,
    };
  }

  const obj = data as Record<string, unknown>;

  // Already in correct format
  if (typeof obj.error_code === 'string' && typeof obj.message === 'string') {
    return {
      error_code: obj.error_code,
      message: obj.message,
      trace_id: typeof obj.trace_id === 'string' ? obj.trace_id : traceId,
      field: typeof obj.field === 'string' ? obj.field : undefined,
      details: obj.details,
    };
  }

  // Platform-admin style: { error: { code, message } }
  if (obj.error && typeof obj.error === 'object') {
    const err = obj.error as Record<string, unknown>;
    return {
      error_code: typeof err.code === 'string' ? err.code : 'API_ERROR',
      message: typeof err.message === 'string' ? err.message : 'Request failed',
      trace_id: typeof err.trace_id === 'string' ? err.trace_id : traceId,
      field: typeof err.field === 'string' ? err.field : undefined,
      details: err.details,
    };
  }

  // FastAPI structured detail
  if (obj.detail && typeof obj.detail === 'object' && !Array.isArray(obj.detail)) {
    const detail = obj.detail as Record<string, unknown>;
    return {
      error_code: typeof detail.code === 'string' ? detail.code : 'VALIDATION_FAILED',
      message: typeof detail.message === 'string' ? detail.message : 'Validation failed',
      trace_id: typeof detail.trace_id === 'string' ? detail.trace_id : traceId,
      field: typeof detail.field === 'string' ? detail.field : undefined,
    };
  }

  // FastAPI string detail
  if (typeof obj.detail === 'string') {
    return {
      error_code: status === 401 ? 'UNAUTHORIZED' : status === 403 ? 'FORBIDDEN' : 'API_ERROR',
      message: obj.detail,
      trace_id: traceId,
    };
  }

  // Pydantic validation errors (array)
  if (Array.isArray(obj.detail) && obj.detail.length > 0) {
    const first = obj.detail[0] as Record<string, unknown>;
    const loc = first.loc as unknown[];
    const field = loc && loc.length > 0 ? String(loc[loc.length - 1]) : undefined;
    return {
      error_code: 'VALIDATION_FAILED',
      message: typeof first.msg === 'string' ? first.msg : 'Validation failed',
      trace_id: traceId,
      field: field !== 'body' ? field : undefined,
    };
  }

  // Legacy: { success: false, error: string }
  if (obj.success === false && typeof obj.error === 'string') {
    return {
      error_code: typeof obj.error_code === 'string' ? obj.error_code : 'API_ERROR',
      message: obj.error,
      trace_id: traceId,
    };
  }

  // Generic message
  if (typeof obj.message === 'string') {
    return {
      error_code: 'API_ERROR',
      message: obj.message,
      trace_id: traceId,
    };
  }

  return {
    error_code: 'UNKNOWN_ERROR',
    message: 'An unexpected error occurred',
    trace_id: traceId,
  };
}

/**
 * Convert ProxyResult to NextResponse with proper headers.
 *
 * GUARANTEES:
 * - Error responses always have { error_code, message, trace_id }
 * - Cache-Control: no-store on all responses (auth-protected)
 * - Vary: Cookie header set
 */
export function proxyResultToResponse(result: ProxyResult): NextResponse {
  const headers = {
    'Cache-Control': 'no-store',
    'Vary': 'Cookie',
  };

  // If it's an error, normalize to standard envelope
  if (!result.ok) {
    const normalized = normalizeErrorResponse(result.data, result.traceId, result.status);
    const response = NextResponse.json(normalized, { status: result.status });
    Object.entries(headers).forEach(([k, v]) => response.headers.set(k, v));
    return response;
  }

  // For non-JSON responses, return as-is with headers
  if (typeof result.data === 'string' && !result.contentType?.includes('application/json')) {
    const response = new NextResponse(result.data, {
      status: result.status,
      headers: {
        ...headers,
        ...(result.contentType ? { 'Content-Type': result.contentType } : {}),
      },
    });
    return response;
  }

  const response = NextResponse.json(result.data, { status: result.status });
  Object.entries(headers).forEach(([k, v]) => response.headers.set(k, v));
  return response;
}

/**
 * Simple proxy handler that forwards request to backend.
 *
 * Usage in route.ts:
 * ```
 * export async function GET(request: NextRequest) {
 *   return simpleProxy(request, '/api/v1/roster/plans');
 * }
 * ```
 */
export async function simpleProxy(
  request: NextRequest,
  backendPath: string,
  options: Omit<ProxyOptions, 'method' | 'body'> = {}
): Promise<NextResponse> {
  const session = await getSessionCookie();
  if (!session) {
    return unauthorizedResponse(options.traceId);
  }

  const method = request.method as ProxyOptions['method'];
  let body: unknown;

  if (['POST', 'PUT', 'PATCH'].includes(method || '')) {
    try {
      body = await request.json();
    } catch {
      // No body or not JSON
    }
  }

  // Forward idempotency key if present
  const idempotencyKey = request.headers.get('x-idempotency-key');
  const headers: Record<string, string> = {
    ...options.headers,
  };
  if (idempotencyKey) {
    headers['x-idempotency-key'] = idempotencyKey;
  }

  const result = await proxyToBackend(backendPath, session, {
    ...options,
    method,
    body,
    headers,
  });

  return proxyResultToResponse(result);
}
