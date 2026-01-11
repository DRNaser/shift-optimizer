/**
 * SOLVEREIGN V4.4 - Internal RBAC Login BFF Route
 *
 * Proxies login requests to backend and forwards session cookie.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

interface LoginRequest {
  email: string;
  password: string;
  tenant_id?: number;
}

export async function POST(request: NextRequest) {
  try {
    const body: LoginRequest = await request.json();

    // Forward Origin header for CSRF validation
    const origin = request.headers.get("origin");
    const referer = request.headers.get("referer");

    // Forward login request to backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Forward CSRF-related headers
        ...(origin && { Origin: origin }),
        ...(referer && { Referer: referer }),
      },
      body: JSON.stringify(body),
      credentials: "include",
    });

    // Get response data - handle non-JSON responses gracefully
    let data: Record<string, unknown>;
    const contentType = backendResponse.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await backendResponse.json();
    } else {
      // Non-JSON response (e.g., HTML error page from proxy)
      const text = await backendResponse.text();
      console.error("Login BFF: non-JSON response from backend:", text.slice(0, 200));
      data = {
        success: false,
        error_code: "BACKEND_ERROR",
        message: "Backend returned non-JSON response",
      };
    }

    // Create response
    const response = NextResponse.json(data, {
      status: backendResponse.status,
    });

    // Forward ALL Set-Cookie headers from backend
    // IMPORTANT: headers.get("set-cookie") is unreliable in Node.js fetch
    // Use getSetCookie() which returns an array of all Set-Cookie headers
    const setCookies = backendResponse.headers.getSetCookie?.()
      ?? (backendResponse.headers as any).raw?.()?.["set-cookie"]
      ?? [];

    // Diagnostic logging (no secrets - just cookie names)
    if (process.env.NODE_ENV !== "production") {
      const cookieNames = setCookies.map((c: string) => c.split("=")[0]);
      console.log(`Login BFF: backend status=${backendResponse.status}, cookies=${cookieNames.join(",") || "none"}`);
    }

    for (const cookie of setCookies) {
      response.headers.append("set-cookie", cookie);
    }

    // Fallback for single cookie (older Node versions)
    if (setCookies.length === 0) {
      const singleCookie = backendResponse.headers.get("set-cookie");
      if (singleCookie) {
        const cookieName = singleCookie.split("=")[0];
        if (process.env.NODE_ENV !== "production") {
          console.log(`Login BFF: fallback cookie=${cookieName}`);
        }
        response.headers.set("set-cookie", singleCookie);
      } else if (backendResponse.status === 200) {
        // SUCCESS but no cookie - this is a problem!
        console.error("Login BFF: backend returned 200 but NO Set-Cookie header!");
      }
    }

    // Also set cache control headers
    response.headers.set("Cache-Control", "no-store, no-cache, must-revalidate");
    response.headers.set("Pragma", "no-cache");

    return response;
  } catch (error) {
    console.error("Login BFF error:", error);
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
