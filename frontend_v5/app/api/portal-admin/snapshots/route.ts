/**
 * SOLVEREIGN V4.4 - Portal Admin Snapshots BFF Route
 *
 * Returns list of available snapshots for the current tenant/site.
 * RBAC: portal.summary.read permission required.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  // Get session cookie from request
  const sessionCookie = request.cookies.get("__Host-sv_platform_session");

  if (!sessionCookie) {
    return NextResponse.json(
      { error: "Not authenticated", error_code: "NO_SESSION" },
      { status: 401 }
    );
  }

  try {
    const response = await fetch(
      `${BACKEND_URL}/api/v1/portal/dashboard/snapshots`,
      {
        headers: {
          "Content-Type": "application/json",
          Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
        },
        cache: "no-store",
      }
    );

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: data.detail || `Backend error: ${response.status}` },
        { status: response.status }
      );
    }

    const data = await response.json();

    const res = NextResponse.json(data);
    res.headers.set("Cache-Control", "no-store, no-cache, must-revalidate");
    res.headers.set("Pragma", "no-cache");
    return res;
  } catch (error) {
    console.error("Portal admin snapshots error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
