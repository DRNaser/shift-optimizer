// =============================================================================
// SOLVEREIGN V4.3 - Portal Admin Summary BFF Route
// =============================================================================
// Proxies dashboard summary requests to backend with auth.
// RBAC: Dispatcher or Approver role required.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const snapshotId = searchParams.get("snapshot_id");

  if (!snapshotId) {
    return NextResponse.json(
      { error: "snapshot_id is required" },
      { status: 400 }
    );
  }

  try {
    // TODO: Extract auth token from request and verify role
    // For now, forward request to backend

    const response = await fetch(
      `${BACKEND_URL}/api/v1/portal/dashboard/summary?snapshot_id=${snapshotId}`,
      {
        headers: {
          "Content-Type": "application/json",
          // TODO: Add auth headers from request
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
    return NextResponse.json(data);
  } catch (error) {
    console.error("Portal admin summary error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
