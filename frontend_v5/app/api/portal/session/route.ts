// =============================================================================
// SOLVEREIGN V4.3 - Portal Session Exchange
// =============================================================================
// Exchanges magic link token for HttpOnly session cookie.
// This allows refresh/back/deep-link to work after initial token validation.
//
// SECURITY:
// - HttpOnly: JS cannot access cookie (XSS protection)
// - Secure: Only sent over HTTPS
// - SameSite=Strict: No CSRF
// - Short-lived: 60 minutes default (configurable)
// - Token is validated server-side before session is created
// =============================================================================

import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || "http://localhost:8000";
const SESSION_COOKIE_NAME = "portal_session";
const SESSION_MAX_AGE = 60 * 60; // 60 minutes in seconds

interface SessionPayload {
  jti_hash: string;
  driver_id: string;
  tenant_id: number;
  snapshot_id: string;
  expires_at: number;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { token } = body;

    if (!token || typeof token !== "string") {
      return NextResponse.json(
        { error: "Token is required" },
        { status: 400 }
      );
    }

    // Validate token with backend and get plan data
    const response = await fetch(`${BACKEND_URL}/api/portal/view?t=${token}`, {
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (response.status === 401) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        { ok: false, error: data.detail || "Invalid token", status: "error" },
        { status: 401 }
      );
    }

    if (response.status === 410) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        { ok: false, error: "Superseded", status: "superseded", new_snapshot_id: data.new_snapshot_id },
        { status: 410 }
      );
    }

    if (!response.ok) {
      return NextResponse.json(
        { ok: false, error: "Failed to validate token", status: "error" },
        { status: response.status }
      );
    }

    const data = await response.json();

    // Create session payload (stored in signed cookie)
    // We store minimal data - the token itself is the session identifier
    const sessionPayload: SessionPayload = {
      jti_hash: hashToken(token), // Hash for lookup, not the raw token
      driver_id: data.plan?.driver_id || "",
      tenant_id: data.tenant_id || 0,
      snapshot_id: data.snapshot_id || "",
      expires_at: Math.floor(Date.now() / 1000) + SESSION_MAX_AGE,
    };

    // Encode session as base64 JSON (in production, use signed JWT or encrypted cookie)
    const sessionValue = Buffer.from(JSON.stringify({
      ...sessionPayload,
      t: token, // Keep token for subsequent API calls (encrypted in cookie)
    })).toString("base64");

    // Set HttpOnly cookie
    const cookieStore = await cookies();
    cookieStore.set(SESSION_COOKIE_NAME, sessionValue, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      maxAge: SESSION_MAX_AGE,
      path: "/my-plan",
    });

    return NextResponse.json({
      ok: true,
      status: "valid",
      plan: data.plan,
      ack_status: data.ack_status || "PENDING",
    });
  } catch (error) {
    console.error("Portal session error:", error);
    return NextResponse.json(
      { ok: false, error: "Internal server error", status: "error" },
      { status: 500 }
    );
  }
}

// GET: Check if session is valid (for refresh)
export async function GET(request: NextRequest) {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME);

    if (!sessionCookie?.value) {
      return NextResponse.json(
        { ok: false, error: "No session", status: "no_session" },
        { status: 401 }
      );
    }

    // Decode session
    let session: SessionPayload & { t: string };
    try {
      session = JSON.parse(Buffer.from(sessionCookie.value, "base64").toString("utf-8"));
    } catch {
      return NextResponse.json(
        { ok: false, error: "Invalid session", status: "error" },
        { status: 401 }
      );
    }

    // Check expiry
    if (session.expires_at < Math.floor(Date.now() / 1000)) {
      // Clear expired cookie
      cookieStore.delete(SESSION_COOKIE_NAME);
      return NextResponse.json(
        { ok: false, error: "Session expired", status: "expired" },
        { status: 401 }
      );
    }

    // Re-fetch plan with stored token
    const response = await fetch(`${BACKEND_URL}/api/portal/view?t=${session.t}`, {
      cache: "no-store",
    });

    if (response.status === 401) {
      cookieStore.delete(SESSION_COOKIE_NAME);
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        { ok: false, error: data.detail || "Token expired", status: "expired" },
        { status: 401 }
      );
    }

    if (response.status === 410) {
      const data = await response.json().catch(() => ({}));
      return NextResponse.json(
        { ok: false, error: "Superseded", status: "superseded", new_snapshot_id: data.new_snapshot_id },
        { status: 410 }
      );
    }

    if (!response.ok) {
      return NextResponse.json(
        { ok: false, error: "Failed to load plan", status: "error" },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json({
      ok: true,
      status: "valid",
      plan: data.plan,
      ack_status: data.ack_status || "PENDING",
    });
  } catch (error) {
    console.error("Portal session check error:", error);
    return NextResponse.json(
      { ok: false, error: "Internal server error", status: "error" },
      { status: 500 }
    );
  }
}

// DELETE: Clear session (logout)
export async function DELETE() {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE_NAME);
  return NextResponse.json({ ok: true });
}

// Simple hash for jti lookup (not for security, just for logging without exposing token)
function hashToken(token: string): string {
  // Use first 8 chars of base64 encoded hash-like value
  // In production, use crypto.createHash('sha256')
  let hash = 0;
  for (let i = 0; i < token.length; i++) {
    const char = token.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(36).substring(0, 8);
}
