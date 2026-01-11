// =============================================================================
// SOLVEREIGN - Auth Module Exports
// =============================================================================
//
// !!! DEPRECATED (V4.4.0) !!!
// ===========================
// This module and all Entra ID/MSAL exports are DEPRECATED as of V4.4.0 (2026-01-09).
// Internal RBAC with email/password authentication is now the default.
//
// MIGRATION:
// - Admin auth: /platform/login page with email/password
// - Driver portal: Magic links with session cookies
// - API auth: BFF routes forward session cookies automatically
//
// These exports are kept for backwards compatibility only.
// DO NOT USE for new development.
//
// =============================================================================
// Original documentation (historical):
// Centralized exports for authentication functionality.
// =============================================================================

// Configuration
export {
  msalConfig,
  loginRequest,
  apiRequest,
  AppRoles,
  type AppRole,
  isMsalConfigured,
  getMsalConfigStatus,
} from './msal-config';

// Context and hooks
export {
  AuthProvider,
  useAuth,
  useRequireAuth,
  type AuthUser,
  type AuthState,
  type AuthContextValue,
} from './auth-context';

// Protected routes
export {
  ProtectedRoute,
  RequirePlatformAdmin,
  RequireTenantAdmin,
  RequireApprover,
  DefaultLoading,
  DefaultUnauthenticated,
  DefaultUnauthorized,
} from './protected-route';

// Authenticated API client
export {
  useAuthenticatedFetch,
  useApi,
  type ApiResponse,
  type ApiError,
  type FetchOptions,
  type PublishRequest,
  type PublishResponse,
  type FreezeStatusResponse,
  type PlanSnapshot,
} from './api-client';
