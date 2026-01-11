/**
 * SOLVEREIGN V4.4 - Internal RBAC User Info BFF Route
 *
 * Returns current authenticated user info from session cookie.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// Session cookie names (prod: __Host-, dev: without prefix)
const SESSION_COOKIE_NAMES = ['__Host-sv_platform_session', 'sv_platform_session'];

export async function GET(request: NextRequest) {
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

    if (!sessionCookie) {
      return NextResponse.json(
        {
          success: false,
          error_code: "NO_SESSION",
          message: "Not authenticated",
        },
        { status: 401 }
      );
    }

    // Forward request to backend with the cookie name that was found
    const backendResponse = await fetch(`${BACKEND_URL}/api/auth/me`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Cookie: `${cookieName}=${sessionCookie.value}`,
      },
      credentials: "include",
    });

    // Get response data
    const data = await backendResponse.json();

    // Create response - wrap in expected format for frontend
    const wrappedData = backendResponse.ok
      ? { success: true, user: data }
      : { success: false, ...data };

    const response = NextResponse.json(wrappedData, {
      status: backendResponse.status,
    });

    // Set cache control headers
    response.headers.set("Cache-Control", "no-store, no-cache, must-revalidate");
    response.headers.set("Pragma", "no-cache");

    return response;
  } catch (error) {
    console.error("Me BFF error:", error);
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
