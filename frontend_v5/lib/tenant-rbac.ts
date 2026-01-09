// =============================================================================
// SOLVEREIGN Tenant RBAC - Server-Side Role-Based Access Control
// =============================================================================
// This module provides server-side RBAC checking for BFF routes.
// IMPORTANT: This is NOT just UI disabling - it's actual permission enforcement.
//
// Roles:
// - PLANNER: Can read, import, validate, create scenarios, run solver
// - APPROVER: All PLANNER + can publish, lock, freeze, approve
// - TENANT_ADMIN: All APPROVER + can manage tenant settings
// =============================================================================

import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

// =============================================================================
// TYPES
// =============================================================================

export type TenantRole = 'PLANNER' | 'APPROVER' | 'TENANT_ADMIN';

export interface TenantContext {
  tenantCode: string;
  siteCode: string;
  userEmail: string;
  userRole: TenantRole;
  isBlocked: boolean;
}

export interface Permission {
  action: string;
  resource: string;
  requiredRoles: TenantRole[];
}

// =============================================================================
// PERMISSION DEFINITIONS
// =============================================================================

export const PERMISSIONS: Record<string, Permission> = {
  // Read operations - all roles can read
  'read:status': { action: 'read', resource: 'status', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'read:imports': { action: 'read', resource: 'imports', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'read:teams': { action: 'read', resource: 'teams', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'read:scenarios': { action: 'read', resource: 'scenarios', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'read:plans': { action: 'read', resource: 'plans', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'read:evidence': { action: 'read', resource: 'evidence', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'read:repair': { action: 'read', resource: 'repair', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'read:freeze': { action: 'read', resource: 'freeze', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Import/Upload - PLANNER can import
  'upload:stops': { action: 'upload', resource: 'stops', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'upload:teams': { action: 'upload', resource: 'teams', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Validate - PLANNER can validate
  'validate:import': { action: 'validate', resource: 'import', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'validate:teams': { action: 'validate', resource: 'teams', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Accept/Reject imports - PLANNER can accept/reject
  'accept:import': { action: 'accept', resource: 'import', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },
  'reject:import': { action: 'reject', resource: 'import', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Publish (2-person gate) - ONLY APPROVER+ can publish
  'publish:teams': { action: 'publish', resource: 'teams', requiredRoles: ['APPROVER', 'TENANT_ADMIN'] },

  // Create scenarios - PLANNER can create
  'create:scenario': { action: 'create', resource: 'scenario', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Run solver - PLANNER can solve
  'solve:scenario': { action: 'solve', resource: 'scenario', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Run audit - PLANNER can audit
  'audit:plan': { action: 'audit', resource: 'plan', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Lock plan - ONLY APPROVER+ can lock
  'lock:plan': { action: 'lock', resource: 'plan', requiredRoles: ['APPROVER', 'TENANT_ADMIN'] },

  // Freeze stops - ONLY APPROVER+ can freeze
  'freeze:stops': { action: 'freeze', resource: 'stops', requiredRoles: ['APPROVER', 'TENANT_ADMIN'] },

  // Generate evidence - PLANNER can generate
  'generate:evidence': { action: 'generate', resource: 'evidence', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Create repair event - PLANNER can create
  'create:repair': { action: 'create', resource: 'repair', requiredRoles: ['PLANNER', 'APPROVER', 'TENANT_ADMIN'] },

  // Execute repair - ONLY APPROVER+ can execute
  'execute:repair': { action: 'execute', resource: 'repair', requiredRoles: ['APPROVER', 'TENANT_ADMIN'] },

  // Tenant admin operations - ONLY TENANT_ADMIN
  'manage:tenant': { action: 'manage', resource: 'tenant', requiredRoles: ['TENANT_ADMIN'] },
};

// =============================================================================
// CONTEXT HELPERS
// =============================================================================

/**
 * Get tenant context from cookies (server-side).
 * This is the source of truth for user identity in BFF routes.
 */
export async function getTenantContext(): Promise<TenantContext> {
  const cookieStore = await cookies();

  const tenantCode = cookieStore.get('sv_tenant_code')?.value || '';
  const siteCode = cookieStore.get('sv_current_site')?.value || '';
  const userEmail = cookieStore.get('sv_user_email')?.value || '';
  const userRole = (cookieStore.get('sv_user_role')?.value as TenantRole) || 'PLANNER';
  const isBlocked = cookieStore.get('sv_tenant_blocked')?.value === 'true';

  return { tenantCode, siteCode, userEmail, userRole, isBlocked };
}

// =============================================================================
// PERMISSION CHECKING
// =============================================================================

/**
 * Check if user has permission for an action.
 * Returns true if user's role is in the required roles list.
 */
export function hasPermission(userRole: TenantRole, permissionKey: string): boolean {
  const permission = PERMISSIONS[permissionKey];
  if (!permission) {
    // Unknown permission = deny by default
    console.error(`Unknown permission key: ${permissionKey}`);
    return false;
  }
  return permission.requiredRoles.includes(userRole);
}

/**
 * Check if operation is a write operation (requires unblocked tenant).
 */
export function isWriteOperation(permissionKey: string): boolean {
  const writeActions = ['upload', 'validate', 'accept', 'reject', 'publish', 'create', 'solve', 'audit', 'lock', 'freeze', 'generate', 'execute', 'manage'];
  const permission = PERMISSIONS[permissionKey];
  return permission ? writeActions.includes(permission.action) : false;
}

// =============================================================================
// MIDDLEWARE HELPERS
// =============================================================================

/**
 * Create a 403 Forbidden response with structured error.
 */
export function forbiddenResponse(message: string, details?: Record<string, unknown>) {
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
 * Create a 503 Service Unavailable response (tenant blocked).
 */
export function blockedResponse(reason: string) {
  return NextResponse.json(
    {
      code: 'TENANT_BLOCKED',
      message: `Tenant is blocked: ${reason}`,
      escalation_url: '/platform/escalations',
    },
    { status: 503 }
  );
}

/**
 * Require permission for a BFF route.
 * Returns null if permitted, or a NextResponse error if denied.
 *
 * Usage:
 * ```
 * const denied = await requirePermission('lock:plan');
 * if (denied) return denied;
 * // ... proceed with operation
 * ```
 */
export async function requirePermission(
  permissionKey: string
): Promise<NextResponse | null> {
  const ctx = await getTenantContext();

  // Check if tenant is blocked for write operations
  if (isWriteOperation(permissionKey) && ctx.isBlocked) {
    return blockedResponse('Tenant writes are disabled due to active escalation');
  }

  // Check role permission
  if (!hasPermission(ctx.userRole, permissionKey)) {
    const permission = PERMISSIONS[permissionKey];
    return forbiddenResponse(
      `Permission denied: ${permissionKey}`,
      {
        user_role: ctx.userRole,
        required_roles: permission?.requiredRoles || [],
        action: permission?.action,
        resource: permission?.resource,
      }
    );
  }

  return null;
}

/**
 * Require idempotency key for write operations.
 * Returns null if key is present, or a NextResponse error if missing.
 *
 * IMPORTANT: BFF enforces KEY PRESENCE only.
 * Actual deduplication/replay protection is the BACKEND's responsibility.
 * The BFF passes the key 1:1 to the backend via X-Idempotency-Key header.
 *
 * @see backend_py/api/dependencies.py - IdempotencyKeyDep for actual dedupe logic
 */
export function requireIdempotencyKey(
  idempotencyKey: string | null
): NextResponse | null {
  if (!idempotencyKey) {
    return NextResponse.json(
      {
        code: 'MISSING_IDEMPOTENCY_KEY',
        message: 'X-Idempotency-Key header is required for write operations',
      },
      { status: 400 }
    );
  }
  return null;
}

// =============================================================================
// ROLE HIERARCHY HELPERS
// =============================================================================

const ROLE_HIERARCHY: Record<TenantRole, number> = {
  PLANNER: 1,
  APPROVER: 2,
  TENANT_ADMIN: 3,
};

/**
 * Check if role1 >= role2 in hierarchy.
 */
export function roleAtLeast(role1: TenantRole, role2: TenantRole): boolean {
  return ROLE_HIERARCHY[role1] >= ROLE_HIERARCHY[role2];
}

/**
 * Get display name for role.
 */
export function getRoleDisplayName(role: TenantRole): string {
  switch (role) {
    case 'PLANNER': return 'Planer';
    case 'APPROVER': return 'Freigeber';
    case 'TENANT_ADMIN': return 'Tenant-Admin';
    default: return role;
  }
}
