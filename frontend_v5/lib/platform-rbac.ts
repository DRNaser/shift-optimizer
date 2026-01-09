// =============================================================================
// SOLVEREIGN Platform RBAC - Server-Side Role-Based Access Control
// =============================================================================
// This module provides server-side RBAC checking for PLATFORM BFF routes.
//
// IMPORTANT: This is SEPARATE from tenant-rbac.ts
// - Tenant RBAC: Tenant-scoped operations (sv_tenant_code cookie)
// - Platform RBAC: Platform admin operations (sv_platform_session cookie)
//
// Platform Roles:
// - platform_viewer: Can read platform data, view escalations
// - platform_admin: All viewer + can create/modify orgs, tenants, resolve escalations
// =============================================================================

import { cookies, headers } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';

// =============================================================================
// TYPES
// =============================================================================

export type PlatformRole = 'platform_viewer' | 'platform_admin';

export interface PlatformContext {
  userId: string;
  userEmail: string;
  userName: string;
  role: PlatformRole;
  sessionValid: boolean;
}

export interface PlatformPermission {
  action: string;
  resource: string;
  requiredRoles: PlatformRole[];
}

// =============================================================================
// PERMISSION DEFINITIONS
// =============================================================================

export const PLATFORM_PERMISSIONS: Record<string, PlatformPermission> = {
  // Read operations - all platform roles can read
  'platform:read:orgs': { action: 'read', resource: 'orgs', requiredRoles: ['platform_viewer', 'platform_admin'] },
  'platform:read:tenants': { action: 'read', resource: 'tenants', requiredRoles: ['platform_viewer', 'platform_admin'] },
  'platform:read:sites': { action: 'read', resource: 'sites', requiredRoles: ['platform_viewer', 'platform_admin'] },
  'platform:read:escalations': { action: 'read', resource: 'escalations', requiredRoles: ['platform_viewer', 'platform_admin'] },
  'platform:read:status': { action: 'read', resource: 'status', requiredRoles: ['platform_viewer', 'platform_admin'] },
  'platform:read:entitlements': { action: 'read', resource: 'entitlements', requiredRoles: ['platform_viewer', 'platform_admin'] },

  // Write operations - platform_admin only
  'platform:create:org': { action: 'create', resource: 'org', requiredRoles: ['platform_admin'] },
  'platform:create:tenant': { action: 'create', resource: 'tenant', requiredRoles: ['platform_admin'] },
  'platform:create:site': { action: 'create', resource: 'site', requiredRoles: ['platform_admin'] },
  'platform:create:escalation': { action: 'create', resource: 'escalation', requiredRoles: ['platform_admin'] },
  'platform:resolve:escalation': { action: 'resolve', resource: 'escalation', requiredRoles: ['platform_admin'] },

  // Update operations - platform_admin only
  'platform:update:org': { action: 'update', resource: 'org', requiredRoles: ['platform_admin'] },
  'platform:update:tenant': { action: 'update', resource: 'tenant', requiredRoles: ['platform_admin'] },
  'platform:update:entitlement': { action: 'update', resource: 'entitlement', requiredRoles: ['platform_admin'] },

  // Dangerous operations - platform_admin only
  'platform:deactivate:org': { action: 'deactivate', resource: 'org', requiredRoles: ['platform_admin'] },
  'platform:deactivate:tenant': { action: 'deactivate', resource: 'tenant', requiredRoles: ['platform_admin'] },
};

// =============================================================================
// COOKIE NAMES
// =============================================================================

/**
 * Cookie names for platform auth.
 *
 * __Host- prefix enforces: Secure=true, Path=/, no Domain attribute
 * This prevents subdomain attacks and cookie scope manipulation.
 */
export const PLATFORM_COOKIE_NAMES = {
  // Security-critical cookies with __Host- prefix
  session: '__Host-sv_platform_session',  // HttpOnly, Secure, SameSite=Strict
  userId: '__Host-sv_platform_user_id',   // HttpOnly, Secure, SameSite=Strict
  csrf: '__Host-sv_csrf_token',           // NOT HttpOnly (JS must read), Secure, SameSite=Strict

  // Display-only cookies (NOT trusted for auth decisions)
  userEmail: 'sv_platform_user_email',
  userName: 'sv_platform_user_name',
  role: 'sv_platform_role',
} as const;

// =============================================================================
// CONTEXT HELPERS
// =============================================================================

/**
 * Get platform context from cookies (server-side).
 * Uses SEPARATE cookies from tenant context.
 *
 * Trust anchor: __Host-sv_platform_session cookie (HttpOnly, Secure, SameSite=Strict)
 *
 * Session token format: {payload}.{signature}
 * - payload: base64({userId}:{role}:{expiry})
 * - signature: HMAC-SHA256(payload, secret)
 */
export async function getPlatformContext(): Promise<PlatformContext> {
  const cookieStore = await cookies();

  // SECURITY: Only accept __Host- prefixed cookie in production
  // Fallback to old name ONLY in development (for migration)
  let sessionToken: string | undefined;
  if (process.env.NODE_ENV === 'production') {
    // Production: ONLY accept __Host- prefixed cookie
    sessionToken = cookieStore.get(PLATFORM_COOKIE_NAMES.session)?.value;
  } else {
    // Development: Allow fallback for migration (temporary)
    sessionToken =
      cookieStore.get(PLATFORM_COOKIE_NAMES.session)?.value ||
      cookieStore.get('sv_platform_session')?.value;
  }

  // Same for userId
  let userId: string;
  if (process.env.NODE_ENV === 'production') {
    userId = cookieStore.get(PLATFORM_COOKIE_NAMES.userId)?.value || '';
  } else {
    userId =
      cookieStore.get(PLATFORM_COOKIE_NAMES.userId)?.value ||
      cookieStore.get('sv_platform_user_id')?.value ||
      '';
  }

  const userEmail = cookieStore.get(PLATFORM_COOKIE_NAMES.userEmail)?.value || '';
  const userName = cookieStore.get(PLATFORM_COOKIE_NAMES.userName)?.value || '';
  const roleCookie = cookieStore.get(PLATFORM_COOKIE_NAMES.role)?.value;

  // SECURITY: Validate session token (signature + expiry)
  const validation = validateSessionToken(sessionToken);

  // Role from signed token takes precedence over cookie (if token is valid)
  // This prevents role spoofing via client-readable cookie
  const role = validation.valid && validation.role
    ? validation.role
    : (roleCookie as PlatformRole) || 'platform_viewer';

  return {
    userId: validation.valid && validation.userId ? validation.userId : userId,
    userEmail,
    userName,
    role,
    sessionValid: validation.valid,
  };
}

// =============================================================================
// SESSION TOKEN CONFIGURATION
// =============================================================================

/**
 * Session token TTL configuration.
 * SECURITY: Lower TTL = faster rotation = less exposure window.
 */
const SESSION_CONFIG = {
  // Default TTL: 4 hours (reduced from 24h for security)
  DEFAULT_TTL_SECONDS: 4 * 60 * 60,
  // Maximum allowed TTL: 8 hours
  MAX_TTL_SECONDS: 8 * 60 * 60,
  // Grace period for clock skew: 30 seconds
  CLOCK_SKEW_SECONDS: 30,
} as const;

/**
 * Get session secrets for rotation support.
 * SECURITY: Supports multiple secrets for graceful rotation.
 *
 * Env vars:
 * - SOLVEREIGN_SESSION_SECRET: Current primary secret
 * - SOLVEREIGN_SESSION_SECRET_PREV: Previous secret (for rotation)
 * - SOLVEREIGN_INTERNAL_SECRET: Fallback
 *
 * Rotation procedure:
 * 1. Set SOLVEREIGN_SESSION_SECRET_PREV = current secret
 * 2. Set SOLVEREIGN_SESSION_SECRET = new secret
 * 3. Deploy (both secrets valid during transition)
 * 4. After TTL expires, remove SOLVEREIGN_SESSION_SECRET_PREV
 */
function getSessionSecrets(): string[] {
  const secrets: string[] = [];

  // Primary secret (current)
  const primary = process.env.SOLVEREIGN_SESSION_SECRET;
  if (primary) secrets.push(primary);

  // Previous secret (rotation grace period)
  const previous = process.env.SOLVEREIGN_SESSION_SECRET_PREV;
  if (previous) secrets.push(previous);

  // Fallback to internal secret
  const internal = process.env.SOLVEREIGN_INTERNAL_SECRET;
  if (internal && !secrets.includes(internal)) secrets.push(internal);

  // Dev fallback (ONLY in non-production)
  if (secrets.length === 0) {
    if (process.env.NODE_ENV === 'production') {
      console.error('CRITICAL: No session secret configured in production!');
      // Return empty - will cause all tokens to fail
      return [];
    }
    secrets.push('dev_secret_unsafe');
  }

  return secrets;
}

/**
 * Timing-safe string comparison to prevent timing attacks.
 * SECURITY: Always compares full length regardless of mismatch position.
 */
function timingSafeEqual(a: string, b: string): boolean {
  const crypto = require('crypto');
  if (a.length !== b.length) {
    // Still do the comparison to maintain constant time
    // but result will be false
    const dummy = Buffer.alloc(a.length, 0);
    crypto.timingSafeEqual(dummy, Buffer.from(a));
    return false;
  }
  return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
}

/**
 * Validate session token signature and expiry.
 * Token format: {base64_payload}.{signature}
 * Payload: {userId}:{role}:{expiry_unix}
 *
 * SECURITY:
 * - Timing-safe signature comparison
 * - Secret rotation support (tries all valid secrets)
 * - Clock skew tolerance
 */
function validateSessionToken(token: string | undefined): {
  valid: boolean;
  userId?: string;
  role?: PlatformRole;
  error?: string;
} {
  if (!token) {
    return { valid: false, error: 'No token' };
  }

  // Split token into payload and signature
  const parts = token.split('.');
  if (parts.length !== 2) {
    // Legacy dev-session format (unsigned)
    // SECURITY: Only allow with explicit flag AND non-production
    if (
      process.env.NODE_ENV !== 'production' &&
      process.env.ALLOW_LEGACY_DEV_SESSION === 'true' &&
      token.startsWith('dev-session-')
    ) {
      console.warn('SECURITY: Legacy unsigned dev-session token accepted (dev only)');
      return { valid: true, error: 'Legacy dev token (dev only)' };
    }
    return { valid: false, error: 'Invalid token format' };
  }

  const [payloadB64, signature] = parts;

  // Get all valid secrets (for rotation support)
  const secrets = getSessionSecrets();
  if (secrets.length === 0) {
    return { valid: false, error: 'No secrets configured' };
  }

  // Try each secret (for rotation support)
  // SECURITY: Use timing-safe comparison
  let signatureValid = false;
  for (const secret of secrets) {
    const expectedSig = createHmacSignature(payloadB64, secret);
    if (timingSafeEqual(signature, expectedSig)) {
      signatureValid = true;
      break;
    }
  }

  if (!signatureValid) {
    return { valid: false, error: 'Invalid signature' };
  }

  // Decode and parse payload
  try {
    const payload = Buffer.from(payloadB64, 'base64').toString('utf8');
    const [userId, role, expiryStr] = payload.split(':');

    // Check expiry (with clock skew tolerance)
    const expiry = parseInt(expiryStr, 10);
    const now = Date.now() / 1000;
    if (isNaN(expiry) || now > expiry + SESSION_CONFIG.CLOCK_SKEW_SECONDS) {
      return { valid: false, error: 'Token expired' };
    }

    // Validate role
    const validRoles: PlatformRole[] = ['platform_viewer', 'platform_admin'];
    if (!validRoles.includes(role as PlatformRole)) {
      return { valid: false, error: 'Invalid role in token' };
    }

    return { valid: true, userId, role: role as PlatformRole };
  } catch {
    return { valid: false, error: 'Failed to decode payload' };
  }
}

/**
 * Create HMAC-SHA256 signature for session token.
 */
function createHmacSignature(payload: string, secret: string): string {
  const crypto = require('crypto');
  return crypto.createHmac('sha256', secret).update(payload).digest('hex');
}

/**
 * Create a signed session token.
 * Exported for use by dev-login and future auth endpoints.
 *
 * @param userId - User identifier
 * @param role - Platform role
 * @param expirySeconds - Token TTL (default: 4 hours, max: 8 hours)
 */
export function createSignedSessionToken(
  userId: string,
  role: PlatformRole,
  expirySeconds: number = SESSION_CONFIG.DEFAULT_TTL_SECONDS
): string {
  // Enforce maximum TTL
  const ttl = Math.min(expirySeconds, SESSION_CONFIG.MAX_TTL_SECONDS);

  const expiry = Math.floor(Date.now() / 1000) + ttl;
  const payload = `${userId}:${role}:${expiry}`;
  const payloadB64 = Buffer.from(payload).toString('base64');

  // Always use primary secret for signing
  const secrets = getSessionSecrets();
  const secret = secrets[0] || 'dev_secret_unsafe';
  const signature = createHmacSignature(payloadB64, secret);

  return `${payloadB64}.${signature}`;
}

// =============================================================================
// PERMISSION CHECKING
// =============================================================================

/**
 * Check if user has permission for a platform action.
 */
export function hasPlatformPermission(userRole: PlatformRole, permissionKey: string): boolean {
  const permission = PLATFORM_PERMISSIONS[permissionKey];
  if (!permission) {
    console.error(`Unknown platform permission key: ${permissionKey}`);
    return false;
  }
  return permission.requiredRoles.includes(userRole);
}

/**
 * Check if operation is a write operation.
 */
export function isPlatformWriteOperation(permissionKey: string): boolean {
  const writeActions = ['create', 'update', 'delete', 'resolve', 'deactivate'];
  const permission = PLATFORM_PERMISSIONS[permissionKey];
  return permission ? writeActions.includes(permission.action) : false;
}

// =============================================================================
// CSRF PROTECTION
// =============================================================================

/**
 * Validate CSRF token for write operations.
 * Implements double-submit cookie pattern.
 *
 * Client must send X-CSRF-Token header matching the CSRF cookie.
 *
 * SECURITY:
 * - Uses timing-safe comparison to prevent timing attacks
 * - Supports both __Host- and legacy cookie names during migration
 */
export async function validateCsrfToken(request: NextRequest): Promise<boolean> {
  const cookieStore = await cookies();
  const headerStore = await headers();

  // Get CSRF token from cookie (__Host- prefixed, with fallback for migration)
  let cookieToken: string | undefined;
  if (process.env.NODE_ENV === 'production') {
    // Production: only accept __Host- prefixed cookie
    cookieToken = cookieStore.get(PLATFORM_COOKIE_NAMES.csrf)?.value;
  } else {
    // Development: allow fallback for migration
    cookieToken =
      cookieStore.get(PLATFORM_COOKIE_NAMES.csrf)?.value ||
      cookieStore.get('sv_csrf_token')?.value;
  }

  const headerToken = headerStore.get('x-csrf-token');

  if (!cookieToken || !headerToken) {
    return false;
  }

  // SECURITY: Timing-safe comparison
  return timingSafeEqual(cookieToken, headerToken);
}

// =============================================================================
// MIDDLEWARE HELPERS
// =============================================================================

/**
 * Create a 401 Unauthorized response.
 */
export function unauthorizedResponse(message: string = 'Not authenticated') {
  return NextResponse.json(
    {
      code: 'UNAUTHORIZED',
      message,
      login_url: '/platform/login',
    },
    { status: 401 }
  );
}

/**
 * Create a 403 Forbidden response.
 */
export function platformForbiddenResponse(message: string, details?: Record<string, unknown>) {
  return NextResponse.json(
    {
      code: 'FORBIDDEN',
      message,
      details,
    },
    { status: 403 }
  );
}

/**
 * Create a 400 Bad Request response for missing CSRF token.
 */
export function csrfErrorResponse() {
  return NextResponse.json(
    {
      code: 'CSRF_VALIDATION_FAILED',
      message: 'Missing or invalid CSRF token. Include X-CSRF-Token header.',
    },
    { status: 400 }
  );
}

/**
 * Require platform authentication + permission for a BFF route.
 * Returns null if permitted, or a NextResponse error if denied.
 *
 * Usage:
 * ```
 * const denied = await requirePlatformPermission('platform:create:org', request);
 * if (denied) return denied;
 * // ... proceed with operation
 * ```
 */
export async function requirePlatformPermission(
  permissionKey: string,
  request?: NextRequest
): Promise<NextResponse | null> {
  const ctx = await getPlatformContext();

  // 1. Check authentication (session must be valid)
  if (!ctx.sessionValid) {
    return unauthorizedResponse('Platform session required. Please log in.');
  }

  // 2. Check CSRF token for write operations
  if (isPlatformWriteOperation(permissionKey) && request) {
    const csrfValid = await validateCsrfToken(request);
    if (!csrfValid) {
      return csrfErrorResponse();
    }
  }

  // 3. Check role permission
  if (!hasPlatformPermission(ctx.role, permissionKey)) {
    const permission = PLATFORM_PERMISSIONS[permissionKey];
    return platformForbiddenResponse(
      `Platform permission denied: ${permissionKey}`,
      {
        user_role: ctx.role,
        required_roles: permission?.requiredRoles || [],
        action: permission?.action,
        resource: permission?.resource,
      }
    );
  }

  return null;
}

/**
 * Require idempotency key for platform write operations.
 * Returns null if key is present, or a NextResponse error if missing.
 *
 * IMPORTANT: BFF enforces KEY PRESENCE only.
 * Actual deduplication is the BACKEND's responsibility.
 */
export function requirePlatformIdempotencyKey(
  idempotencyKey: string | null
): NextResponse | null {
  if (!idempotencyKey) {
    return NextResponse.json(
      {
        code: 'MISSING_IDEMPOTENCY_KEY',
        message: 'X-Idempotency-Key header is required for platform write operations',
      },
      { status: 400 }
    );
  }
  return null;
}

/**
 * Combined guard for platform POST routes.
 * Checks: auth + permission + CSRF + idempotency key
 */
export async function requirePlatformWriteAccess(
  permissionKey: string,
  request: NextRequest
): Promise<NextResponse | null> {
  // 1. Check permission (includes auth + CSRF for writes)
  const permissionError = await requirePlatformPermission(permissionKey, request);
  if (permissionError) return permissionError;

  // 2. Check idempotency key
  const idempotencyKey = request.headers.get('x-idempotency-key');
  const idempotencyError = requirePlatformIdempotencyKey(idempotencyKey);
  if (idempotencyError) return idempotencyError;

  return null;
}

// =============================================================================
// SESSION HELPERS
// =============================================================================

/**
 * Get resolved_by identifier for API calls (audit trail).
 * Format: "email|name" for logging.
 */
export async function getPlatformResolvedBy(): Promise<string> {
  const ctx = await getPlatformContext();
  return `${ctx.userEmail}|${ctx.userName}`;
}

/**
 * Check if current user has platform admin role.
 */
export async function isPlatformAdmin(): Promise<boolean> {
  const ctx = await getPlatformContext();
  return ctx.sessionValid && ctx.role === 'platform_admin';
}

// =============================================================================
// DEV/TEST HELPERS
// =============================================================================

/**
 * Create mock platform session cookies for development/testing.
 * NEVER use in production!
 */
export function createDevPlatformSession(): {
  'sv_platform_session': string;
  'sv_platform_user_id': string;
  'sv_platform_user_email': string;
  'sv_platform_user_name': string;
  'sv_platform_role': PlatformRole;
  'sv_csrf_token': string;
} {
  const csrfToken = `dev-csrf-${Date.now()}`;
  return {
    'sv_platform_session': `dev-session-${Date.now()}`,
    'sv_platform_user_id': 'dev-admin-001',
    'sv_platform_user_email': 'admin@solvereign.com',
    'sv_platform_user_name': 'Dev Admin',
    'sv_platform_role': 'platform_admin',
    'sv_csrf_token': csrfToken,
  };
}
