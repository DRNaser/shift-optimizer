// =============================================================================
// SOLVEREIGN V4.3 - Portal Read Receipt (Session-based)
// =============================================================================
// Records read receipt using session cookie token.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || "http://localhost:8000";
const SESSION_COOKIE_NAME = "portal_session";

export async function POST(request: NextRequest) {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME);

    if (!sessionCookie?.value) {
      return NextResponse.json(
        { error: "No session" },
        { status: 401 }
      );
    }

    // Decode session to get token
    let session: { t: string; expires_at: number };
    try {
      session = JSON.parse(Buffer.from(sessionCookie.value, "base64").toString("utf-8"));
    } catch {
      return NextResponse.json(
        { error: "Invalid session" },
        { status: 401 }
      );
    }

    // Check expiry
    if (session.expires_at < Math.floor(Date.now() / 1000)) {
      return NextResponse.json(
        { error: "Session expired" },
        { status: 401 }
      );
    }

    // Forward to backend
    const response = await fetch(`${BACKEND_URL}/api/portal/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: session.t }),
      cache: "no-store",
    });

    if (!response.ok) {
      // Silent fail for read tracking - not critical
      return NextResponse.json({ ok: true });
    }

    return NextResponse.json({ ok: true });
  } catch {
    // Silent fail for read tracking
    return NextResponse.json({ ok: true });
  }
}
