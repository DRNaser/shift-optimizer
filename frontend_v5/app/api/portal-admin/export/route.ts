// =============================================================================
// SOLVEREIGN V4.3 - Portal Admin Export BFF Route
// =============================================================================
// Exports driver list as CSV.
// RBAC: Dispatcher role required.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || "http://localhost:8000";

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

  try {
    const url = new URL(`${BACKEND_URL}/api/v1/portal/dashboard/export`);
    url.searchParams.set("snapshot_id", snapshotId);
    url.searchParams.set("filter", filter);
    url.searchParams.set("format", "csv");

    const response = await fetch(url.toString(), {
      headers: {
        "Content-Type": "application/json",
        Accept: "text/csv",
        // TODO: Add auth headers from request
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

    return new NextResponse(csv, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="portal-export-${snapshotId.slice(0, 8)}.csv"`,
      },
    });
  } catch (error) {
    console.error("Portal admin export error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
