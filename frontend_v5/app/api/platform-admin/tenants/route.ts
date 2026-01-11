/**
 * SOLVEREIGN V4.6 - Platform Admin Tenants BFF Route
 *
 * Proxies tenant management requests to backend.
 * Requires platform_admin role (tenant_id=0).
 *
 * Error Contract:
 * All errors are normalized to: { error: { code, message, field?, details? } }
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

interface NormalizedError {
  error: {
    code: string;
    message: string;
    field?: string;
    details?: unknown;
  };
}

/**
 * Normalize backend error responses to consistent format.
 * Input formats handled:
 * - { error: { code, message, field?, details? } } (new format - pass through)
 * - { detail: { code, message, field? } } (FastAPI HTTPException with structured detail)
 * - { detail: string } (FastAPI HTTPException with string)
 * - { message: string } (generic)
 * - Pydantic validation errors (array of detail)
 */
function normalizeError(data: unknown, fallbackMessage: string): NormalizedError {
  if (!data || typeof data !== "object") {
    return { error: { code: "UNKNOWN_ERROR", message: fallbackMessage } };
  }

  const obj = data as Record<string, unknown>;

  // Already in correct format
  if (obj.error && typeof obj.error === "object") {
    const err = obj.error as Record<string, unknown>;
    return {
      error: {
        code: typeof err.code === "string" ? err.code : "UNKNOWN_ERROR",
        message: typeof err.message === "string" ? err.message : fallbackMessage,
        field: typeof err.field === "string" ? err.field : undefined,
        details: err.details,
      },
    };
  }

  // FastAPI HTTPException format with structured detail
  if (obj.detail && typeof obj.detail === "object" && !Array.isArray(obj.detail)) {
    const detail = obj.detail as Record<string, unknown>;
    return {
      error: {
        code: typeof detail.code === "string" ? detail.code : "VALIDATION_FAILED",
        message: typeof detail.message === "string" ? detail.message : fallbackMessage,
        field: typeof detail.field === "string" ? detail.field : undefined,
        details: detail.details,
      },
    };
  }

  // Pydantic validation errors (array of detail)
  if (Array.isArray(obj.detail) && obj.detail.length > 0) {
    const firstError = obj.detail[0] as Record<string, unknown> | undefined;
    if (firstError && firstError.msg) {
      const loc = firstError.loc as unknown[];
      const field = loc && loc.length > 0 ? String(loc[loc.length - 1]) : undefined;
      return {
        error: {
          code: "VALIDATION_FAILED",
          message: String(firstError.msg),
          field: field !== "body" ? field : undefined,
        },
      };
    }
  }

  // FastAPI HTTPException with string detail
  if (typeof obj.detail === "string") {
    return { error: { code: "API_ERROR", message: obj.detail } };
  }

  // Generic message
  if (typeof obj.message === "string") {
    return { error: { code: "API_ERROR", message: obj.message } };
  }

  return { error: { code: "UNKNOWN_ERROR", message: fallbackMessage } };
}

/**
 * GET /api/platform-admin/tenants
 * List all tenants (platform admin only)
 */
export async function GET(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        normalizeError(null, "Not authenticated"),
        { status: 401 }
      );
    }

    // Get query params
    const { searchParams } = new URL(request.url);
    const includeCounts = searchParams.get("include_counts") || "false";

    const backendResponse = await fetch(
      `${BACKEND_URL}/api/platform/tenants?include_counts=${includeCounts}`,
      {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
          Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
        },
      }
    );

    const data = await backendResponse.json();

    // If error, normalize it
    if (!backendResponse.ok) {
      return NextResponse.json(
        normalizeError(data, "Failed to load tenants"),
        { status: backendResponse.status }
      );
    }

    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Platform tenants BFF error:", error);
    return NextResponse.json(
      normalizeError(null, "Internal server error"),
      { status: 500 }
    );
  }
}

/**
 * POST /api/platform-admin/tenants
 * Create a new tenant (platform admin only)
 */
export async function POST(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { error: { code: "UNAUTHENTICATED", message: "Not authenticated" } },
        { status: 401 }
      );
    }

    const body = await request.json();

    const backendResponse = await fetch(`${BACKEND_URL}/api/platform/tenants`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
      },
      body: JSON.stringify(body),
    });

    const data = await backendResponse.json();

    // If error, normalize it
    if (!backendResponse.ok) {
      return NextResponse.json(
        normalizeError(data, "Failed to create tenant"),
        { status: backendResponse.status }
      );
    }

    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Platform tenants BFF error:", error);
    return NextResponse.json(
      { error: { code: "INTERNAL_ERROR", message: "Internal server error" } },
      { status: 500 }
    );
  }
}
