// =============================================================================
// SOLVEREIGN Platform Auth Utilities
// =============================================================================
// Platform admin authentication context and user identity.
// Integrates with Entra ID authentication via MSAL.
// =============================================================================

import { AppRoles, type AuthUser } from './auth';

/**
 * Platform user identity for audit logging and governance.
 */
export interface PlatformUser {
  /** User principal name (email) */
  email: string;
  /** Display name */
  name: string;
  /** User ID from auth provider */
  id: string;
  /** Platform admin role */
  role: 'platform_admin' | 'platform_viewer';
  /** Tenant ID from Entra ID */
  tenantId?: string;
}

/**
 * Convert AuthUser from Entra ID to PlatformUser.
 */
export function authUserToPlatformUser(authUser: AuthUser): PlatformUser {
  const isPlatformAdmin = authUser.roles.includes(AppRoles.PLATFORM_ADMIN);

  return {
    email: authUser.email,
    name: authUser.name,
    id: authUser.id,
    role: isPlatformAdmin ? 'platform_admin' : 'platform_viewer',
    tenantId: authUser.tenantId,
  };
}

/**
 * Get current platform user identity.
 *
 * DEPRECATED: Use useAuth() hook in React components instead.
 * This function is only for legacy code and server-side contexts.
 *
 * In production, components should use the useAuth() hook which:
 * - Provides real Entra ID user from MSAL
 * - Handles token refresh automatically
 * - Exposes role checking methods
 *
 * This function falls back to:
 * 1. localStorage override (dev/testing only)
 * 2. Mock admin user (ONLY when MSAL not configured)
 *
 * @deprecated Use useAuth() hook in React components
 */
export function getPlatformUser(): PlatformUser {
  // Check localStorage for dev/testing override
  // NOTE: This should ONLY be used in development environments
  if (typeof window !== 'undefined') {
    const override = localStorage.getItem('sv_platform_user');
    if (override) {
      try {
        console.warn(
          '[SOLVEREIGN] Using localStorage override for platform user. ' +
          'This should only be used in development.'
        );
        return JSON.parse(override);
      } catch {
        // Ignore parse errors
      }
    }
  }

  // Fallback for server-side or when auth not initialized
  // WARNING: This mock user should NOT be used in production
  // Real implementation uses useAuth() hook in components
  console.warn(
    '[SOLVEREIGN] Using mock platform user. ' +
    'Configure MSAL environment variables for production auth.'
  );
  return {
    email: 'admin@solvereign.com',
    name: 'Platform Admin (Mock)',
    id: 'mock-admin-001',
    role: 'platform_admin',
  };
}

/**
 * Get resolved_by identifier for API calls.
 * Format: "email|name" for audit trail.
 */
export function getResolvedByIdentifier(): string {
  const user = getPlatformUser();
  return `${user.email}|${user.name}`;
}

/**
 * Get resolved_by identifier from AuthUser.
 */
export function getResolvedByFromAuthUser(authUser: AuthUser): string {
  return `${authUser.email}|${authUser.name}`;
}

/**
 * Check if current user has platform admin role.
 */
export function isPlatformAdmin(): boolean {
  const user = getPlatformUser();
  return user.role === 'platform_admin';
}

/**
 * Check if AuthUser has platform admin role.
 */
export function isAuthUserPlatformAdmin(authUser: AuthUser): boolean {
  return authUser.roles.includes(AppRoles.PLATFORM_ADMIN);
}

/**
 * Check if AuthUser can approve plans.
 */
export function canApprove(authUser: AuthUser): boolean {
  return (
    authUser.roles.includes(AppRoles.APPROVER) ||
    authUser.roles.includes(AppRoles.TENANT_ADMIN) ||
    authUser.roles.includes(AppRoles.PLATFORM_ADMIN)
  );
}

/**
 * Set platform user for development/testing.
 * Only works in browser environment.
 */
export function setDevPlatformUser(user: PlatformUser): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem('sv_platform_user', JSON.stringify(user));
  }
}

/**
 * Clear dev platform user override.
 */
export function clearDevPlatformUser(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('sv_platform_user');
  }
}
