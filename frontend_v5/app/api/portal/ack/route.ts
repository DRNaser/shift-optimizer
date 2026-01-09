// =============================================================================
// SOLVEREIGN V4.3 - Portal Acknowledgment (Session-based)
// =============================================================================
// Submits driver acknowledgment using session cookie token.
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
        { error: "No session", detail: "Ihre Sitzung ist abgelaufen. Bitte öffnen Sie den Link erneut." },
        { status: 401 }
      );
    }

    // Decode session to get token
    let session: { t: string; expires_at: number };
    try {
      session = JSON.parse(Buffer.from(sessionCookie.value, "base64").toString("utf-8"));
    } catch {
      return NextResponse.json(
        { error: "Invalid session", detail: "Ungültige Sitzung" },
        { status: 401 }
      );
    }

    // Check expiry
    if (session.expires_at < Math.floor(Date.now() / 1000)) {
      cookieStore.delete(SESSION_COOKIE_NAME);
      return NextResponse.json(
        { error: "Session expired", detail: "Ihre Sitzung ist abgelaufen. Bitte öffnen Sie den Link erneut." },
        { status: 401 }
      );
    }

    // Get ack data from request
    const body = await request.json();
    const { status, reason_code, free_text } = body;

    if (!status || !["ACCEPTED", "DECLINED"].includes(status)) {
      return NextResponse.json(
        { error: "Invalid status", detail: "Ungültiger Status" },
        { status: 400 }
      );
    }

    // Forward to backend with token from session
    const response = await fetch(`${BACKEND_URL}/api/portal/ack`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: session.t,
        status,
        reason_code,
        free_text,
      }),
      cache: "no-store",
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: "Ack failed", detail: data.detail || "Fehler beim Bestätigen" },
        { status: response.status }
      );
    }

    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("Portal ack error:", error);
    return NextResponse.json(
      { error: "Internal error", detail: "Interner Fehler" },
      { status: 500 }
    );
  }
}
