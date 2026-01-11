/**
 * SOLVEREIGN V4.4 - Internal RBAC Logout BFF Route
 *
 * Proxies logout requests to backend and clears session cookie.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// Session cookie names (prod: __Host-, dev: without prefix)
const SESSION_COOKIE_NAMES = ['__Host-sv_platform_session', 'sv_platform_session'];

export async function POST(request: NextRequest) {
  try {
    // Get session cookie from request (check both prod and dev names)
    let sessionCookie = null;
    let cookieName = '';
    for (const name of SESSION_COOKIE_NAMES) {
      const cookie = request.cookies.get(name);
      if (cookie) {
        sessionCookie = cookie;
        cookieName = name;
        break;
      }
    }

    // Forward logout request to backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(sessionCookie && { Cookie: `${cookieName}=${sessionCookie.value}` }),
      },
      credentials: "include",
    });

    // Get response data
    const data = await backendResponse.json();

    // Create response
    const response = NextResponse.json(data, {
      status: backendResponse.status,
    });

    // Clear ALL session cookies (prod, dev, and legacy)
    response.cookies.delete("__Host-sv_platform_session");
    response.cookies.delete("sv_platform_session");
    response.cookies.delete("admin_session");

    // Set cache control headers
    response.headers.set("Cache-Control", "no-store, no-cache, must-revalidate");
    response.headers.set("Pragma", "no-cache");

    return response;
  } catch (error) {
    console.error("Logout BFF error:", error);
    return NextResponse.json(
      {
        success: false,
        error_code: "BFF_ERROR",
        message: "Internal server error",
      },
      { status: 500 }
    );
  }
}
