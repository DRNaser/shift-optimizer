// =============================================================================
// SOLVEREIGN V4.3 - Portal Admin Snapshots BFF Route
// =============================================================================
// Returns list of available snapshots for the current tenant/site.
// RBAC: Dispatcher role required.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  try {
    const response = await fetch(
      `${BACKEND_URL}/api/v1/portal/dashboard/snapshots`,
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
    console.error("Portal admin snapshots error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
