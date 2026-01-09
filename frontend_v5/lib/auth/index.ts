// =============================================================================
// SOLVEREIGN - Auth Module Exports
// =============================================================================
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
