// =============================================================================
// SOLVEREIGN - Protected Route Components
// =============================================================================
// Components for protecting routes that require authentication or specific roles.
// =============================================================================

'use client';

import { type ReactNode } from 'react';
import { useAuth, useRequireAuth, type AppRole } from './auth-context';

// =============================================================================
// TYPES
// =============================================================================

interface ProtectedRouteProps {
  children: ReactNode;
  /** Required roles (user must have at least one) */
  requiredRoles?: AppRole[];
  /** Custom loading component */
  loadingComponent?: ReactNode;
  /** Custom unauthorized component */
  unauthorizedComponent?: ReactNode;
  /** Custom unauthenticated component */
  unauthenticatedComponent?: ReactNode;
}

// =============================================================================
// COMPONENTS
// =============================================================================

/**
 * Protects a route requiring authentication.
 * Optionally requires specific roles.
 */
export function ProtectedRoute({
  children,
  requiredRoles,
  loadingComponent,
  unauthorizedComponent,
  unauthenticatedComponent,
}: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, isConfigured } = useAuth();
  const { isAuthorized, isLoading: authCheckLoading } = useRequireAuth(requiredRoles);

  // If MSAL not configured, allow access (dev mode)
  if (!isConfigured) {
    return <>{children}</>;
  }

  // Show loading while checking auth
  if (isLoading || authCheckLoading) {
    return loadingComponent ? <>{loadingComponent}</> : <DefaultLoading />;
  }

  // Not authenticated
  if (!isAuthenticated) {
    return unauthenticatedComponent ? (
      <>{unauthenticatedComponent}</>
    ) : (
      <DefaultUnauthenticated />
    );
  }

  // Authenticated but not authorized (missing required role)
  if (requiredRoles && !isAuthorized) {
    return unauthorizedComponent ? (
      <>{unauthorizedComponent}</>
    ) : (
      <DefaultUnauthorized requiredRoles={requiredRoles} />
    );
  }

  return <>{children}</>;
}

/**
 * Requires user to be a platform admin.
 */
export function RequirePlatformAdmin({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute requiredRoles={['Platform.Admin']}>
      {children}
    </ProtectedRoute>
  );
}

/**
 * Requires user to be a tenant admin.
 */
export function RequireTenantAdmin({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute requiredRoles={['Tenant.Admin', 'Platform.Admin']}>
      {children}
    </ProtectedRoute>
  );
}

/**
 * Requires user to be an approver.
 */
export function RequireApprover({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute requiredRoles={['Approver', 'Tenant.Admin', 'Platform.Admin']}>
      {children}
    </ProtectedRoute>
  );
}

// =============================================================================
// DEFAULT FALLBACK COMPONENTS
// =============================================================================

function DefaultLoading() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto" />
        <p className="mt-4 text-gray-600">Loading...</p>
      </div>
    </div>
  );
}

function DefaultUnauthenticated() {
  const { login, loginRedirect, isConfigured } = useAuth();

  if (!isConfigured) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center max-w-md p-8 bg-white rounded-lg shadow">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">
            Authentication Not Configured
          </h1>
          <p className="text-gray-600 mb-6">
            Azure AD authentication is not configured. Set the required environment
            variables to enable authentication.
          </p>
          <code className="block text-left text-sm bg-gray-100 p-4 rounded mb-4">
            NEXT_PUBLIC_AZURE_AD_CLIENT_ID<br />
            NEXT_PUBLIC_AZURE_AD_TENANT_ID
          </code>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="text-center max-w-md p-8 bg-white rounded-lg shadow">
        <h1 className="text-2xl font-bold text-gray-900 mb-4">
          Sign In Required
        </h1>
        <p className="text-gray-600 mb-6">
          Please sign in with your organizational account to continue.
        </p>
        <div className="space-y-3">
          <button
            onClick={() => login()}
            className="w-full px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Sign In with Microsoft
          </button>
          <button
            onClick={() => loginRedirect()}
            className="w-full px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
          >
            Sign In (Redirect)
          </button>
        </div>
      </div>
    </div>
  );
}

function DefaultUnauthorized({ requiredRoles }: { requiredRoles: AppRole[] }) {
  const { user, logout } = useAuth();

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="text-center max-w-md p-8 bg-white rounded-lg shadow">
        <div className="text-6xl mb-4">🔒</div>
        <h1 className="text-2xl font-bold text-gray-900 mb-4">
          Access Denied
        </h1>
        <p className="text-gray-600 mb-4">
          You don&apos;t have permission to access this page.
        </p>
        <div className="text-sm text-gray-500 mb-6">
          <p>Your roles: {user?.roles.join(', ') || 'None'}</p>
          <p>Required: {requiredRoles.join(' or ')}</p>
        </div>
        <div className="space-y-3">
          <button
            onClick={() => window.history.back()}
            className="w-full px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
          >
            Go Back
          </button>
          <button
            onClick={() => logout()}
            className="w-full px-4 py-2 text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
          >
            Sign Out
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// EXPORTS
// =============================================================================

export { DefaultLoading, DefaultUnauthenticated, DefaultUnauthorized };
