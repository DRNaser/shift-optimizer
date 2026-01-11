/**
 * SOLVEREIGN V4.4 - Portal Admin Export BFF Route
 *
 * Exports driver list as CSV.
 * RBAC: portal.export.read permission required.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const snapshotId = searchParams.get("snapshot_id");
  const filter = searchParams.get("filter") || "ALL";

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
    const url = new URL(`${BACKEND_URL}/api/v1/portal/dashboard/export`);
    url.searchParams.set("snapshot_id", snapshotId);
    url.searchParams.set("filter", filter);
    url.searchParams.set("format", "csv");

    const response = await fetch(url.toString(), {
      headers: {
        "Content-Type": "application/json",
        Accept: "text/csv",
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

    const csv = await response.text();

    const res = new NextResponse(csv, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="portal-export-${snapshotId.slice(0, 8)}.csv"`,
        "Cache-Control": "no-store, no-cache, must-revalidate",
        Pragma: "no-cache",
      },
    });
    return res;
  } catch (error) {
    console.error("Portal admin export error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
