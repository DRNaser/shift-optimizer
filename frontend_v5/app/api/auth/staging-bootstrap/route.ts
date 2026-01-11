// =============================================================================
// SOLVEREIGN BFF - Staging Bootstrap API
// =============================================================================
// Creates a platform admin session using a secret header.
// CONTROLLED ENVIRONMENT ONLY - for automated testing and preflight checks.
//
// SECURITY HARDENING:
// - Disabled by default (STAGING_BOOTSTRAP_ENABLED must be "true")
// - Requires x-bootstrap-secret header (timing-safe comparison)
// - Returns 403 (not 404) when disabled - endpoint existence is not secret
// - __Host- cookie prefix for session (Secure, Path=/, no Domain)
// - SameSite=Strict on all cookies
// - Short TTL (15 minutes)
//
// Contract:
// - POST /api/auth/staging-bootstrap
// - Header: x-bootstrap-secret (required)
// - Response: { success: true, csrf_token: "..." }
// - Cookies: __Host-sv_platform_session (CANONICAL), __Host-sv_csrf_token, etc.
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { createSignedSessionToken, type PlatformRole } from '@/lib/platform-rbac';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

// =============================================================================
// CONFIGURATION
// =============================================================================

const BOOTSTRAP_CONFIG = {
  // Session TTL: 15 minutes (short for security)
  SESSION_TTL_SECONDS: 15 * 60,
  // User identity for bootstrap session
  BOOTSTRAP_USER_ID: 'staging-bootstrap-admin',
  BOOTSTRAP_USER_EMAIL: 'staging-bootstrap@solvereign.internal',
  BOOTSTRAP_USER_NAME: 'Staging Bootstrap',
  BOOTSTRAP_ROLE: 'platform_admin' as PlatformRole,
} as const;

// Cookie names - CANONICAL: __Host-sv_platform_session
// Single session cookie across ALL auth flows for reliability
const COOKIE_NAMES = {
  session: '__Host-sv_platform_session',  // CANONICAL session cookie
  userId: '__Host-sv_platform_user_id',
  csrf: '__Host-sv_csrf_token',
  userEmail: 'sv_platform_user_email',
  userName: 'sv_platform_user_name',
  role: 'sv_platform_role',
} as const;

// =============================================================================
// SECURITY HELPERS
// =============================================================================

/**
 * Timing-safe string comparison to prevent timing attacks.
 * SECURITY: Always compares full length regardless of mismatch position.
 */
function timingSafeEqual(a: string, b: string): boolean {
  const crypto = require('crypto');
  if (a.length !== b.length) {
    // Still do the comparison to maintain constant time
    const dummy = Buffer.alloc(a.length, 0);
    crypto.timingSafeEqual(dummy, Buffer.from(a));
    return false;
  }
  return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
}

/**
 * Generate a cryptographically secure random string for CSRF token.
 */
function generateCsrfToken(): string {
  const crypto = require('crypto');
  return crypto.randomBytes(32).toString('hex');
}

/**
 * Check if bootstrap is enabled.
 */
function isBootstrapEnabled(): boolean {
  return process.env.STAGING_BOOTSTRAP_ENABLED === 'true';
}

/**
 * Get the bootstrap secret from environment.
 */
function getBootstrapSecret(): string | null {
  return process.env.STAGING_BOOTSTRAP_SECRET || null;
}

/**
 * Determine if we're running on HTTPS (for Secure cookie flag).
 * In local HTTP, __Host- prefix technically requires Secure,
 * but browsers may allow localhost without it.
 */
function isSecureContext(request: NextRequest): boolean {
  // Check X-Forwarded-Proto (reverse proxy)
  const forwardedProto = request.headers.get('x-forwarded-proto');
  if (forwardedProto === 'https') return true;

  // Check URL scheme
  const url = new URL(request.url);
  if (url.protocol === 'https:') return true;

  // localhost is treated as secure context by browsers
  if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') {
    return true; // Allow __Host- cookies on localhost
  }

  return false;
}

// =============================================================================
// POST /api/auth/staging-bootstrap
// =============================================================================

/**
 * POST /api/auth/staging-bootstrap
 * Creates a platform admin session using secret header authentication.
 *
 * SECURITY:
 * - Requires STAGING_BOOTSTRAP_ENABLED=true
 * - Requires valid x-bootstrap-secret header
 * - Creates short-lived session (15 min)
 * - Returns CSRF token for subsequent write operations
 */
export async function POST(request: NextRequest) {
  // ==========================================================================
  // GATE 1: Check if bootstrap is enabled (fail-closed)
  // ==========================================================================
  if (!isBootstrapEnabled()) {
    return NextResponse.json(
      {
        success: false,
        code: 'BOOTSTRAP_DISABLED',
        message: 'Staging bootstrap is disabled. Set STAGING_BOOTSTRAP_ENABLED=true to enable.',
      },
      { status: 403 }
    );
  }

  // ==========================================================================
  // GATE 2: Validate bootstrap secret
  // ==========================================================================
  const configuredSecret = getBootstrapSecret();
  if (!configuredSecret) {
    console.error('STAGING_BOOTSTRAP_ENABLED is true but STAGING_BOOTSTRAP_SECRET is not set!');
    return NextResponse.json(
      {
        success: false,
        code: 'MISCONFIGURED',
        message: 'Bootstrap secret not configured. Set STAGING_BOOTSTRAP_SECRET env var.',
      },
      { status: 500 }
    );
  }

  const providedSecret = request.headers.get('x-bootstrap-secret');
  if (!providedSecret) {
    return NextResponse.json(
      {
        success: false,
        code: 'MISSING_SECRET',
        message: 'x-bootstrap-secret header is required.',
      },
      { status: 401 }
    );
  }

  // SECURITY: Timing-safe comparison
  if (!timingSafeEqual(providedSecret, configuredSecret)) {
    return NextResponse.json(
      {
        success: false,
        code: 'INVALID_SECRET',
        message: 'Invalid bootstrap secret.',
      },
      { status: 401 }
    );
  }

  // ==========================================================================
  // GATE 3: Create session and set cookies
  // ==========================================================================
  try {
    const isSecure = isSecureContext(request);

    // Generate signed session token (15 min TTL)
    const sessionToken = createSignedSessionToken(
      BOOTSTRAP_CONFIG.BOOTSTRAP_USER_ID,
      BOOTSTRAP_CONFIG.BOOTSTRAP_ROLE,
      BOOTSTRAP_CONFIG.SESSION_TTL_SECONDS
    );

    // Generate CSRF token
    const csrfToken = generateCsrfToken();

    // Set cookies
    const cookieStore = await cookies();

    // __Host- cookies: Secure=true, Path=/, no Domain (REQUIRED for prefix)
    // HttpOnly for session (not accessible to JS)
    const sessionCookieOptions = {
      httpOnly: true,
      secure: isSecure,
      sameSite: 'strict' as const,
      maxAge: BOOTSTRAP_CONFIG.SESSION_TTL_SECONDS,
      path: '/',
      // NO domain attribute - required for __Host- prefix
    };

    // __Host- CSRF cookie: NOT HttpOnly (must be readable by JS for double-submit)
    const csrfCookieOptions = {
      httpOnly: false,
      secure: isSecure,
      sameSite: 'strict' as const,
      maxAge: BOOTSTRAP_CONFIG.SESSION_TTL_SECONDS,
      path: '/',
      // NO domain attribute - required for __Host- prefix
    };

    // Display-only cookies (NOT trusted for auth decisions)
    const displayCookieOptions = {
      httpOnly: false,
      secure: isSecure,
      sameSite: 'strict' as const,
      maxAge: BOOTSTRAP_CONFIG.SESSION_TTL_SECONDS,
      path: '/',
    };

    // Set session cookies with __Host- prefix (CANONICAL)
    cookieStore.set(COOKIE_NAMES.session, sessionToken, sessionCookieOptions);
    cookieStore.set(COOKIE_NAMES.userId, BOOTSTRAP_CONFIG.BOOTSTRAP_USER_ID, sessionCookieOptions);

    // Set CSRF cookie with __Host- prefix (readable by JS)
    cookieStore.set(COOKIE_NAMES.csrf, csrfToken, csrfCookieOptions);

    // Set display-only cookies (NOT trusted for auth)
    cookieStore.set(COOKIE_NAMES.userEmail, BOOTSTRAP_CONFIG.BOOTSTRAP_USER_EMAIL, displayCookieOptions);
    cookieStore.set(COOKIE_NAMES.userName, BOOTSTRAP_CONFIG.BOOTSTRAP_USER_NAME, displayCookieOptions);
    cookieStore.set(COOKIE_NAMES.role, BOOTSTRAP_CONFIG.BOOTSTRAP_ROLE, displayCookieOptions);

    // Log (no secrets)
    console.log(
      `[staging-bootstrap] Session created for ${BOOTSTRAP_CONFIG.BOOTSTRAP_USER_EMAIL} ` +
      `(role=${BOOTSTRAP_CONFIG.BOOTSTRAP_ROLE}, ttl=${BOOTSTRAP_CONFIG.SESSION_TTL_SECONDS}s)`
    );

    // Return success with CSRF token
    const response = NextResponse.json({
      success: true,
      csrf_token: csrfToken,
      user: {
        id: BOOTSTRAP_CONFIG.BOOTSTRAP_USER_ID,
        email: BOOTSTRAP_CONFIG.BOOTSTRAP_USER_EMAIL,
        name: BOOTSTRAP_CONFIG.BOOTSTRAP_USER_NAME,
        role: BOOTSTRAP_CONFIG.BOOTSTRAP_ROLE,
      },
      session: {
        ttl_seconds: BOOTSTRAP_CONFIG.SESSION_TTL_SECONDS,
        secure: isSecure,
      },
    });

    // Add security headers
    response.headers.set('Cache-Control', 'no-store, no-cache, must-revalidate');
    response.headers.set('Pragma', 'no-cache');
    response.headers.set('X-Content-Type-Options', 'nosniff');

    return response;
  } catch (error) {
    console.error('[staging-bootstrap] Error creating session:', error);
    return NextResponse.json(
      {
        success: false,
        code: 'SESSION_ERROR',
        message: 'Failed to create session.',
      },
      { status: 500 }
    );
  }
}

// =============================================================================
// GET /api/auth/staging-bootstrap
// =============================================================================

/**
 * GET /api/auth/staging-bootstrap
 * Health check - returns whether bootstrap is enabled (no auth required).
 */
export async function GET() {
  const enabled = isBootstrapEnabled();
  const secretConfigured = !!getBootstrapSecret();

  return NextResponse.json({
    endpoint: '/api/auth/staging-bootstrap',
    enabled,
    secret_configured: secretConfigured,
    session_ttl_seconds: BOOTSTRAP_CONFIG.SESSION_TTL_SECONDS,
    usage: enabled
      ? 'POST with x-bootstrap-secret header to create session'
      : 'Set STAGING_BOOTSTRAP_ENABLED=true to enable',
  });
}
