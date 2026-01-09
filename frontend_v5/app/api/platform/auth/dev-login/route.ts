// =============================================================================
// SOLVEREIGN BFF - Dev Login API
// =============================================================================
// DEVELOPMENT ONLY: Sets platform session cookies for testing.
//
// SECURITY HARDENING:
// - Returns 404 (not 403) in production to hide existence
// - IP allowlist for additional protection
// - __Host- cookie prefix for session (Secure, Path=/, no Domain)
// - SameSite=Strict on all cookies
//
// WARNING: This endpoint MUST be disabled in production!
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies, headers } from 'next/headers';
import { createSignedSessionToken, type PlatformRole } from '@/lib/platform-rbac';

// =============================================================================
// SECURITY: IP Allowlist for dev login (PROXY-SAFE)
// =============================================================================

const DEV_LOGIN_ALLOWED_IPS = [
  '127.0.0.1',
  '::1',
  'localhost',
  // Add CI runner IPs if needed
];

// Trusted reverse proxies that can set X-Forwarded-For
// SECURITY: Only trust X-Forwarded-For from these sources
const TRUSTED_PROXIES = [
  '127.0.0.1',
  '::1',
  '10.0.0.0/8',      // Private network (Azure/AWS internal)
  '172.16.0.0/12',   // Private network
  '192.168.0.0/16',  // Private network
];

/**
 * Check if an IP is in a CIDR range (simplified for common cases).
 */
function isInCIDR(ip: string, cidr: string): boolean {
  if (!cidr.includes('/')) {
    return ip === cidr;
  }

  const [network, bits] = cidr.split('/');
  const mask = parseInt(bits, 10);

  // Simple IPv4 check
  const ipParts = ip.split('.').map(Number);
  const netParts = network.split('.').map(Number);

  if (ipParts.length !== 4 || netParts.length !== 4) {
    return false;
  }

  const ipNum = (ipParts[0] << 24) | (ipParts[1] << 16) | (ipParts[2] << 8) | ipParts[3];
  const netNum = (netParts[0] << 24) | (netParts[1] << 16) | (netParts[2] << 8) | netParts[3];
  const maskNum = ~((1 << (32 - mask)) - 1);

  return (ipNum & maskNum) === (netNum & maskNum);
}

/**
 * Check if request comes from trusted proxy.
 */
function isTrustedProxy(proxyIp: string): boolean {
  return TRUSTED_PROXIES.some(trusted => isInCIDR(proxyIp, trusted));
}

/**
 * Get real client IP (proxy-safe).
 * SECURITY: Only trust X-Forwarded-For from trusted proxies.
 */
async function getClientIP(): Promise<string> {
  const headerStore = await headers();

  // Get the connecting IP (immediate source)
  // In Next.js, this would come from the request socket or load balancer
  const connectingIp = headerStore.get('x-real-ip') || 'unknown';

  // Only trust X-Forwarded-For if connecting IP is a trusted proxy
  const forwardedFor = headerStore.get('x-forwarded-for');

  if (forwardedFor && isTrustedProxy(connectingIp)) {
    // X-Forwarded-For: client, proxy1, proxy2
    // Take the LAST untrusted IP (rightmost that's not a trusted proxy)
    const ips = forwardedFor.split(',').map(ip => ip.trim());

    // Walk backwards to find first non-proxy
    for (let i = ips.length - 1; i >= 0; i--) {
      if (!isTrustedProxy(ips[i])) {
        return ips[i];
      }
    }
    // All are proxies? Return the first one
    return ips[0];
  }

  // Not from trusted proxy - use connecting IP directly
  return connectingIp;
}

async function isAllowedIP(): Promise<boolean> {
  const clientIp = await getClientIP();

  // Exact match (no substring matching - security fix)
  return DEV_LOGIN_ALLOWED_IPS.includes(clientIp);
}

// =============================================================================
// SECURITY: Cookie names with __Host- prefix
// =============================================================================

// __Host- prefix enforces: Secure=true, Path=/, no Domain attribute
// This prevents subdomain attacks and cookie scope manipulation
const COOKIE_NAMES = {
  // HttpOnly cookies with __Host- prefix (trust anchors)
  session: '__Host-sv_platform_session',
  userId: '__Host-sv_platform_user_id',
  csrf: '__Host-sv_csrf_token',         // __Host- for CSRF (must still be readable via API)

  // Client-readable cookies (display only, NOT for auth decisions)
  userEmail: 'sv_platform_user_email',
  userName: 'sv_platform_user_name',
  role: 'sv_platform_role',
} as const;

/**
 * POST /api/platform/auth/dev-login
 * Sets development session cookies.
 *
 * SECURITY: DEVELOPMENT ONLY
 * - Returns 404 in production to hide endpoint existence
 * - Validates IP allowlist
 * - Uses __Host- cookie prefix for session
 */
export async function POST(request: NextRequest) {
  // HARD BLOCK: Return 404 in production to hide existence
  if (process.env.NODE_ENV === 'production') {
    // Only allow if explicitly enabled AND on allowlist
    if (!process.env.ALLOW_DEV_LOGIN) {
      return new NextResponse(null, { status: 404 });
    }
    // Even with flag, require IP allowlist in production
    if (!(await isAllowedIP())) {
      return new NextResponse(null, { status: 404 });
    }
  }

  // In development, still check IP allowlist as defense-in-depth
  if (process.env.CHECK_DEV_LOGIN_IP && !(await isAllowedIP())) {
    return NextResponse.json(
      { error: { code: 'FORBIDDEN', message: 'IP not authorized' } },
      { status: 403 }
    );
  }

  try {
    const body = await request.json();
    const { email } = body;

    if (!email) {
      return NextResponse.json(
        { error: { code: 'VALIDATION_ERROR', message: 'Email is required' } },
        { status: 400 }
      );
    }

    // Validate email domain
    const allowedDomains = ['solvereign.com', 'lts.de'];
    const emailDomain = email.split('@')[1]?.toLowerCase();
    const isAllowed = allowedDomains.some(d => emailDomain?.endsWith(d));

    if (!isAllowed) {
      return NextResponse.json(
        { error: { code: 'UNAUTHORIZED', message: 'Email domain not authorized' } },
        { status: 401 }
      );
    }

    // Determine role based on email (for dev purposes)
    const role: PlatformRole = email.includes('admin') ? 'platform_admin' : 'platform_viewer';
    const userId = `dev-user-${email.replace(/[^a-z0-9]/gi, '-')}`;

    // Session TTL: 4 hours (default from SESSION_CONFIG)
    const SESSION_TTL_SECONDS = 4 * 60 * 60;

    // Generate SIGNED session token (HMAC-SHA256)
    // Token contains: userId, role, expiry - all verifiable server-side
    const sessionToken = createSignedSessionToken(userId, role); // Uses 4h default TTL
    const csrfToken = `csrf-${Date.now()}-${Math.random().toString(36).slice(2)}`;

    // Set cookies with security hardening
    const cookieStore = await cookies();

    // __Host- cookies: Secure=true, Path=/, no Domain (REQUIRED)
    // Session cookies are HttpOnly (not accessible to JS)
    const sessionCookieOptions = {
      httpOnly: true,
      secure: true, // Required for __Host- prefix
      sameSite: 'strict' as const,
      maxAge: SESSION_TTL_SECONDS,
      path: '/',
      // NO domain attribute - required for __Host- prefix
    };

    // __Host- CSRF cookie: Secure=true, Path=/, no Domain
    // NOT HttpOnly - must be readable by JS for double-submit pattern
    const csrfCookieOptions = {
      httpOnly: false, // Must be readable by JS
      secure: true,    // Required for __Host- prefix
      sameSite: 'strict' as const,
      maxAge: SESSION_TTL_SECONDS,
      path: '/',
      // NO domain attribute - required for __Host- prefix
    };

    // Client-readable cookies (display only - NOT for auth decisions)
    const displayCookieOptions = {
      httpOnly: false,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict' as const,
      maxAge: SESSION_TTL_SECONDS,
      path: '/',
    };

    // Set session cookies with __Host- prefix
    cookieStore.set(COOKIE_NAMES.session, sessionToken, sessionCookieOptions);
    cookieStore.set(COOKIE_NAMES.userId, userId, sessionCookieOptions);

    // Set CSRF cookie with __Host- prefix (readable by JS)
    cookieStore.set(COOKIE_NAMES.csrf, csrfToken, csrfCookieOptions);

    // Set display-only cookies (NOT trusted for auth)
    cookieStore.set(COOKIE_NAMES.userEmail, email, displayCookieOptions);
    cookieStore.set(COOKIE_NAMES.userName, email.split('@')[0], displayCookieOptions);
    cookieStore.set(COOKIE_NAMES.role, role, displayCookieOptions);

    const response = NextResponse.json({
      success: true,
      user: {
        email,
        name: email.split('@')[0],
        role,
      },
      warning: 'DEV LOGIN - Do not use in production',
    });

    // Add warning header
    response.headers.set('X-Dev-Login-Warning', 'This endpoint is for development only');

    return response;
  } catch {
    return NextResponse.json(
      { error: { code: 'INVALID_JSON', message: 'Invalid request body' } },
      { status: 400 }
    );
  }
}

/**
 * DELETE /api/platform/auth/dev-login
 * Clears platform session cookies (logout).
 *
 * SECURITY: Same protection as POST - 404 in prod, IP allowlist required.
 */
export async function DELETE() {
  // HARD BLOCK: Same protection as POST
  if (process.env.NODE_ENV === 'production') {
    if (!process.env.ALLOW_DEV_LOGIN) {
      return new NextResponse(null, { status: 404 });
    }
    // Even with flag, require IP allowlist in production
    if (!(await isAllowedIP())) {
      return new NextResponse(null, { status: 404 });
    }
  }

  // In development, still check IP allowlist as defense-in-depth
  if (process.env.CHECK_DEV_LOGIN_IP && !(await isAllowedIP())) {
    return NextResponse.json(
      { error: { code: 'FORBIDDEN', message: 'IP not authorized' } },
      { status: 403 }
    );
  }

  const cookieStore = await cookies();

  // Clear all platform cookies (both __Host- and regular)
  const cookiesToClear = Object.values(COOKIE_NAMES);

  for (const name of cookiesToClear) {
    cookieStore.delete(name);
  }

  return NextResponse.json({ success: true });
}
