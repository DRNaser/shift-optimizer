/**
 * SOLVEREIGN V4.5 - Platform Admin Tenant Detail BFF Route
 *
 * Proxies single tenant requests to backend.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

interface RouteContext {
  params: Promise<{ tenantId: string }>;
}

/**
 * GET /api/platform-admin/tenants/[tenantId]
 * Get tenant details
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
      `${BACKEND_URL}/api/platform/tenants/${tenantId}`,
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
    console.error("Platform tenant detail BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}
