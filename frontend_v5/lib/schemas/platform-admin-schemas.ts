/**
 * SOLVEREIGN Platform Admin Schemas (Zod)
 * ========================================
 *
 * Runtime validation for platform admin API responses.
 * Ensures type safety and graceful error handling.
 */

import { z } from 'zod';

// =============================================================================
// TENANT SCHEMAS
// =============================================================================

export const TenantSchema = z.object({
  id: z.number(),
  name: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
  user_count: z.number().optional().default(0),
  site_count: z.number().optional().default(0),
});

export const TenantListResponseSchema = z.array(TenantSchema);

export const TenantDetailSchema = z.object({
  id: z.number(),
  name: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
  updated_at: z.string().optional(),
  config: z.record(z.string(), z.unknown()).optional(),
});

export type Tenant = z.infer<typeof TenantSchema>;
export type TenantDetail = z.infer<typeof TenantDetailSchema>;

// =============================================================================
// SITE SCHEMAS
// =============================================================================

export const SiteSchema = z.object({
  id: z.number(),
  tenant_id: z.number(),
  name: z.string(),
  code: z.string().optional(),
  is_active: z.boolean().default(true),
  created_at: z.string(),
});

export const SiteListResponseSchema = z.array(SiteSchema);

export type Site = z.infer<typeof SiteSchema>;

// =============================================================================
// USER SCHEMAS
// =============================================================================

export const UserBindingSchema = z.object({
  id: z.number().optional(),
  tenant_id: z.number().nullable(),
  tenant_name: z.string().optional(),
  site_id: z.number().nullable(),
  site_name: z.string().optional(),
  role_id: z.number().optional(),
  role_name: z.string(),
  is_active: z.boolean().optional(),
});

export const UserSchema = z.object({
  id: z.string(),
  email: z.string(),
  display_name: z.string().nullable(),
  is_active: z.boolean(),
  is_locked: z.boolean().optional().default(false),
  created_at: z.string(),
  last_login_at: z.string().nullable().optional(),
  bindings: z.array(UserBindingSchema).default([]),
});

export const UserListResponseSchema = z.array(UserSchema);

export type User = z.infer<typeof UserSchema>;
export type UserBinding = z.infer<typeof UserBindingSchema>;

// =============================================================================
// ROLE/PERMISSION SCHEMAS
// =============================================================================

export const RoleSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string().nullable(),
});

export const RoleListResponseSchema = z.array(RoleSchema);

export const PermissionSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string().nullable(),
});

export const PermissionListResponseSchema = z.array(PermissionSchema);

export type Role = z.infer<typeof RoleSchema>;
export type Permission = z.infer<typeof PermissionSchema>;

// =============================================================================
// CONTEXT SCHEMAS
// =============================================================================

export const PlatformContextSchema = z.object({
  tenant_id: z.number().nullable(),
  site_id: z.number().nullable(),
  tenant_name: z.string().optional(),
  site_name: z.string().optional(),
});

export type PlatformContext = z.infer<typeof PlatformContextSchema>;

// =============================================================================
// VALIDATION HELPERS
// =============================================================================

/**
 * Parse tenant list response with Zod validation.
 * Returns validated data or throws validation error.
 */
export function parseTenantListResponse(data: unknown): Tenant[] {
  const result = TenantListResponseSchema.safeParse(data);
  if (!result.success) {
    console.error('[VALIDATION] Tenant list failed:', result.error.issues);
    // Return empty array on validation failure to prevent crash
    return [];
  }
  return result.data;
}

/**
 * Parse user list response with Zod validation.
 * Returns validated data or throws validation error.
 */
export function parseUserListResponse(data: unknown): User[] {
  const result = UserListResponseSchema.safeParse(data);
  if (!result.success) {
    console.error('[VALIDATION] User list failed:', result.error.issues);
    return [];
  }
  return result.data;
}

/**
 * Parse site list response with Zod validation.
 */
export function parseSiteListResponse(data: unknown): Site[] {
  const result = SiteListResponseSchema.safeParse(data);
  if (!result.success) {
    console.error('[VALIDATION] Site list failed:', result.error.issues);
    return [];
  }
  return result.data;
}

/**
 * Parse role list response with Zod validation.
 */
export function parseRoleListResponse(data: unknown): Role[] {
  const result = RoleListResponseSchema.safeParse(data);
  if (!result.success) {
    console.error('[VALIDATION] Role list failed:', result.error.issues);
    return [];
  }
  return result.data;
}
