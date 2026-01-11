/**
 * SOLVEREIGN V4.5 - Platform Admin Sites BFF Route
 *
 * Proxies site management requests to backend.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

interface RouteContext {
  params: Promise<{ tenantId: string }>;
}

/**
 * GET /api/platform-admin/tenants/[tenantId]/sites
 * List sites for a tenant
 */
export async function GET(request: NextRequest, context: RouteContext) {
  try {
    const { tenantId } = await context.params;
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { success: false, error_code: "NO_SESSION", message: "Not authenticated" },
        { status: 401 }
      );
    }

    const backendResponse = await fetch(
      `${BACKEND_URL}/api/platform/tenants/${tenantId}/sites`,
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
    console.error("Platform sites BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}

/**
 * POST /api/platform-admin/tenants/[tenantId]/sites
 * Create a new site
 */
export async function POST(request: NextRequest, context: RouteContext) {
  try {
    const { tenantId } = await context.params;
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { success: false, error_code: "NO_SESSION", message: "Not authenticated" },
        { status: 401 }
      );
    }

    const body = await request.json();

    const backendResponse = await fetch(
      `${BACKEND_URL}/api/platform/tenants/${tenantId}/sites`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
        },
        body: JSON.stringify(body),
      }
    );

    const data = await backendResponse.json();

    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Platform sites BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}
