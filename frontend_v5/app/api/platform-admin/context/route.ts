/**
 * SOLVEREIGN V4.6 - Platform Context BFF Route
 *
 * Proxy for platform admin context switching (GET/POST/DELETE /api/platform/context)
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// GET - Get current active context
export async function GET(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { success: false, error_code: "NO_SESSION", message: "Not authenticated" },
        { status: 401 }
      );
    }

    const backendResponse = await fetch(`${BACKEND_URL}/api/platform/context`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
      },
    });

    const data = await backendResponse.json();
    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Context GET BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}

// POST - Set active context
export async function POST(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { success: false, error_code: "NO_SESSION", message: "Not authenticated" },
        { status: 401 }
      );
    }

    const body = await request.json();

    const backendResponse = await fetch(`${BACKEND_URL}/api/platform/context`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
      },
      body: JSON.stringify(body),
    });

    const data = await backendResponse.json();
    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Context POST BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}

// DELETE - Clear active context
export async function DELETE(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get("__Host-sv_platform_session");

    if (!sessionCookie) {
      return NextResponse.json(
        { success: false, error_code: "NO_SESSION", message: "Not authenticated" },
        { status: 401 }
      );
    }

    const backendResponse = await fetch(`${BACKEND_URL}/api/platform/context`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        Cookie: `__Host-sv_platform_session=${sessionCookie.value}`,
      },
    });

    if (backendResponse.status === 204) {
      return new NextResponse(null, { status: 204 });
    }

    const data = await backendResponse.json();
    return NextResponse.json(data, { status: backendResponse.status });
  } catch (error) {
    console.error("Context DELETE BFF error:", error);
    return NextResponse.json(
      { success: false, error_code: "BFF_ERROR", message: "Internal server error" },
      { status: 500 }
    );
  }
}
