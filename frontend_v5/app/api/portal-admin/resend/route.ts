/**
 * SOLVEREIGN V4.4 - Portal Admin Resend BFF Route
 *
 * Proxies resend requests to backend with session cookie auth + audit logging.
 * RBAC: portal.resend.write permission required.
 * Additional: portal.approve.write for DECLINED/SKIPPED filters.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  // Get session cookie from request
  const sessionCookie = request.cookies.get("__Host-sv_platform_session");

  if (!sessionCookie) {
    return NextResponse.json(
      {
        success: false,
        queued_count: 0,
        skipped_count: 0,
        error: "Not authenticated",
        error_code: "NO_SESSION",
      },
      { status: 401 }
    );
  }

  try {
    const body = await request.json();

    // Validate required fields
    if (!body.snapshot_id) {
      return NextResponse.json(
        {
          success: false,
          queued_count: 0,
          skipped_count: 0,
          error: "snapshot_id is required",
        },
        { status: 400 }
      );
    }

    // Validate guardrails for DECLINED/SKIPPED
    if (body.filter === "DECLINED") {
      if (!body.include_declined) {
        return NextResponse.json(
          {
            success: false,
            queued_count: 0,
            skipped_count: 0,
            error: "include_declined=true required for DECLINED filter",
          },
          { status: 400 }
        );
      }
      if (!body.declined_reason || body.declined_reason.length < 10) {
        return NextResponse.json(
          {
            success: false,
            queued_count: 0,
            skipped_count: 0,
            error: "declined_reason (min 10 chars) required for DECLINED filter",
          },
          { status: 400 }
        );
      }
    }

    if (body.filter === "SKIPPED") {
      if (!body.include_skipped) {
        return NextResponse.json(
          {
            success: false,
            queued_count: 0,
            skipped_count: 0,
            error: "include_skipped=true required for SKIPPED filter",
          },
          { status: 400 }
        );
      }
      if (!body.skipped_reason || body.skipped_reason.length < 10) {
        return NextResponse.json(
          {
            success: false,
            queued_count: 0,
            skipped_count: 0,
            error: "skipped_reason (min 10 chars) required for SKIPPED filter",
          },
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
          Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
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

    const res = NextResponse.json({
      success: true,
      queued_count: data.queued_count || 0,
      skipped_count: data.skipped_count || 0,
    });
    res.headers.set("Cache-Control", "no-store, no-cache, must-revalidate");
    res.headers.set("Pragma", "no-cache");
    return res;
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
