/**
 * SOLVEREIGN V4.5 - Platform Admin Permissions BFF Route
 *
 * Proxies permission listing requests to backend.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/**
 * GET /api/platform-admin/permissions
 * List all permissions
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
    const category = searchParams.get("category");
    const queryString = category ? `?category=${category}` : "";

    const backendResponse = await fetch(`${BACKEND_URL}/api/platform/permissions${queryString}`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
      },
    });

    const data = await backendResponse.json();

    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Platform permissions BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}
