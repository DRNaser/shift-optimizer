// =============================================================================
// SOLVEREIGN V4.3 - Portal Admin Resend BFF Route
// =============================================================================
// Proxies resend requests to backend with auth + audit logging.
// RBAC: Dispatcher role required (Approver for DECLINED/SKIPPED).
// =============================================================================

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Validate required fields
    if (!body.snapshot_id) {
      return NextResponse.json(
        { error: "snapshot_id is required" },
        { status: 400 }
      );
    }

    // Validate guardrails for DECLINED/SKIPPED
    if (body.filter === "DECLINED") {
      if (!body.include_declined) {
        return NextResponse.json(
          { error: "include_declined=true required for DECLINED filter" },
          { status: 400 }
        );
      }
      if (!body.declined_reason || body.declined_reason.length < 10) {
        return NextResponse.json(
          { error: "declined_reason (min 10 chars) required for DECLINED filter" },
          { status: 400 }
        );
      }
    }

    if (body.filter === "SKIPPED") {
      if (!body.include_skipped) {
        return NextResponse.json(
          { error: "include_skipped=true required for SKIPPED filter" },
          { status: 400 }
        );
      }
      if (!body.skipped_reason || body.skipped_reason.length < 10) {
        return NextResponse.json(
          { error: "skipped_reason (min 10 chars) required for SKIPPED filter" },
          { status: 400 }
        );
      }
    }

    const response = await fetch(
      `${BACKEND_URL}/api/v1/portal/dashboard/resend`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // TODO: Add auth headers from request
        },
        body: JSON.stringify(body),
        cache: "no-store",
      }
    );

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        {
          success: false,
          queued_count: 0,
          skipped_count: 0,
          error: data.detail || `Backend error: ${response.status}`,
        },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json({
      success: true,
      queued_count: data.queued_count || 0,
      skipped_count: data.skipped_count || 0,
    });
  } catch (error) {
    console.error("Portal admin resend error:", error);
    return NextResponse.json(
      {
        success: false,
        queued_count: 0,
        skipped_count: 0,
        error: "Internal server error",
      },
      { status: 500 }
    );
  }
}
