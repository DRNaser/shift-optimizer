/**
 * SOLVEREIGN V4.4 - Portal Admin Details BFF Route
 *
 * Proxies driver list requests to backend with session cookie auth.
 * RBAC: portal.details.read permission required.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const snapshotId = searchParams.get("snapshot_id");
  const filter = searchParams.get("filter") || "ALL";
  const page = searchParams.get("page") || "1";
  const pageSize = searchParams.get("page_size") || "50";

  if (!snapshotId) {
    return NextResponse.json(
      { error: "snapshot_id is required" },
      { status: 400 }
    );
  }

  // Get session cookie from request
  const sessionCookie = request.cookies.get("__Host-sv_platform_session");

  if (!sessionCookie) {
    return NextResponse.json(
      { error: "Not authenticated", error_code: "NO_SESSION" },
      { status: 401 }
    );
  }

  try {
    const url = new URL(`${BACKEND_URL}/api/v1/portal/dashboard/details`);
    url.searchParams.set("snapshot_id", snapshotId);
    url.searchParams.set("filter", filter);
    url.searchParams.set("page", page);
    url.searchParams.set("page_size", pageSize);

    const response = await fetch(url.toString(), {
      headers: {
        "Content-Type": "application/json",
        Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
      },
      cache: "no-store",
    });

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
    console.error("Portal admin details error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
