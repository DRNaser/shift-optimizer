/**
 * SOLVEREIGN V4.5 - Platform Admin Sessions BFF Route
 *
 * Proxies session management requests to backend.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/**
 * GET /api/platform-admin/sessions
 * List active sessions
 */
export async function GET(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { success: false, error_code: "NO_SESSION", message: "Not authenticated" },
        { status: 401 }
      );
    }

    // Get query params
    const { searchParams } = new URL(request.url);
    const userId = searchParams.get("user_id");
    const tenantId = searchParams.get("tenant_id");
    const activeOnly = searchParams.get("active_only") ?? "true";

    const params = new URLSearchParams();
    if (userId) params.set("user_id", userId);
    if (tenantId) params.set("tenant_id", tenantId);
    params.set("active_only", activeOnly);

    const backendResponse = await fetch(
      `${BACKEND_URL}/api/platform/sessions?${params.toString()}`,
      {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
          Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
        },
      }
    );

    const data = await backendResponse.json();

    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Platform sessions BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}

/**
 * POST /api/platform-admin/sessions/revoke
 * Revoke sessions
 */
export async function POST(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { success: false, error_code: "NO_SESSION", message: "Not authenticated" },
        { status: 401 }
      );
    }

    const body = await request.json();

    const backendResponse = await fetch(`${BACKEND_URL}/api/platform/sessions/revoke`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
      },
      body: JSON.stringify(body),
    });

    const data = await backendResponse.json();

    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Platform sessions revoke BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}
