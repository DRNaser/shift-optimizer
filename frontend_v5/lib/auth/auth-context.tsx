// =============================================================================
// SOLVEREIGN - Entra ID Authentication Context
// =============================================================================
//
// !!! DEPRECATED (V4.4.0) !!!
// ===========================
// This module is DEPRECATED as of V4.4.0 (2026-01-09).
// Internal RBAC with email/password authentication is now the default.
//
// MIGRATION:
// - Use /platform/login page for admin authentication
// - Session cookies (admin_session) replace MSAL tokens
// - No React context needed - use server-side session validation
//
// This file is kept for reference only. DO NOT USE for new development.
//
// =============================================================================
// Original documentation (historical):
// React context for Entra ID authentication using MSAL.
// Provides user state, login/logout functions, and token acquisition.
// =============================================================================

'use client';

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import {
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
  InteractionRequiredAuthError,
  EventType,
} from '@azure/msal-browser';
import {
  msalConfig,
  loginRequest,
  apiRequest,
  AppRoles,
  type AppRole,
  isMsalConfigured,
} from './msal-config';

// =============================================================================
// TYPES
// =============================================================================

export interface AuthUser {
  /** User object ID from Entra ID */
  id: string;
  /** User principal name (email) */
  email: string;
  /** Display name */
  name: string;
  /** First name */
  firstName?: string;
  /** Last name */
  lastName?: string;
  /** Tenant ID from JWT */
  tenantId?: string;
  /** Application roles from JWT */
  roles: AppRole[];
  /** Raw account info from MSAL */
  account: AccountInfo;
}

export interface AuthState {
  /** Current authenticated user */
  user: AuthUser | null;
  /** Whether authentication is in progress */
  isLoading: boolean;
  /** Whether user is authenticated */
  isAuthenticated: boolean;
  /** Authentication error if any */
  error: Error | null;
  /** Whether MSAL is configured */
  isConfigured: boolean;
}

export interface AuthContextValue extends AuthState {
  /** Login with popup */
  login: () => Promise<void>;
  /** Login with redirect */
  loginRedirect: () => Promise<void>;
  /** Logout */
  logout: () => Promise<void>;
  /** Get access token for API calls */
  getAccessToken: () => Promise<string | null>;
  /** Check if user has specific role */
  hasRole: (role: AppRole) => boolean;
  /** Check if user has any of the specified roles */
  hasAnyRole: (roles: AppRole[]) => boolean;
}

// =============================================================================
// CONTEXT
// =============================================================================

const AuthContext = createContext<AuthContextValue | null>(null);

// =============================================================================
// MSAL INSTANCE (singleton)
// =============================================================================

let msalInstance: PublicClientApplication | null = null;

function getMsalInstance(): PublicClientApplication | null {
  if (typeof window === 'undefined') return null;

  if (!isMsalConfigured()) {
    console.warn('MSAL not configured - auth disabled');
    return null;
  }

  if (!msalInstance) {
    msalInstance = new PublicClientApplication(msalConfig);
  }

  return msalInstance;
}

// =============================================================================
// PROVIDER
// =============================================================================

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
    error: null,
    isConfigured: false,
  });

  // Initialize MSAL
  useEffect(() => {
    const msal = getMsalInstance();

    if (!msal) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        isConfigured: false,
      }));
      return;
    }

    async function initialize() {
      try {
        // Handle redirect callback
        const response = await msal!.handleRedirectPromise();
        if (response) {
          const user = parseAccountToUser(response.account!);
          setState({
            user,
            isLoading: false,
            isAuthenticated: true,
            error: null,
            isConfigured: true,
          });
          return;
        }

        // Check for existing account
        const accounts = msal!.getAllAccounts();
        if (accounts.length > 0) {
          const account = accounts[0];
          msal!.setActiveAccount(account);
          const user = parseAccountToUser(account);
          setState({
            user,
            isLoading: false,
            isAuthenticated: true,
            error: null,
            isConfigured: true,
          });
        } else {
          setState({
            user: null,
            isLoading: false,
            isAuthenticated: false,
            error: null,
            isConfigured: true,
          });
        }
      } catch (error) {
        console.error('MSAL initialization error:', error);
        setState({
          user: null,
          isLoading: false,
          isAuthenticated: false,
          error: error instanceof Error ? error : new Error('Auth initialization failed'),
          isConfigured: true,
        });
      }
    }

    // Listen for account changes
    msal.addEventCallback((event) => {
      if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
        const result = event.payload as AuthenticationResult;
        const user = parseAccountToUser(result.account!);
        setState(prev => ({
          ...prev,
          user,
          isAuthenticated: true,
          error: null,
        }));
      } else if (event.eventType === EventType.LOGOUT_SUCCESS) {
        setState(prev => ({
          ...prev,
          user: null,
          isAuthenticated: false,
        }));
      }
    });

    initialize();
  }, []);

  // Login with popup
  const login = useCallback(async () => {
    const msal = getMsalInstance();
    if (!msal) throw new Error('MSAL not initialized');

    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      const response = await msal.loginPopup(loginRequest);
      msal.setActiveAccount(response.account);
      const user = parseAccountToUser(response.account!);
      setState({
        user,
        isLoading: false,
        isAuthenticated: true,
        error: null,
        isConfigured: true,
      });
    } catch (error) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: error instanceof Error ? error : new Error('Login failed'),
      }));
      throw error;
    }
  }, []);

  // Login with redirect
  const loginRedirect = useCallback(async () => {
    const msal = getMsalInstance();
    if (!msal) throw new Error('MSAL not initialized');

    try {
      setState(prev => ({ ...prev, isLoading: true, error: null }));
      await msal.loginRedirect(loginRequest);
    } catch (error) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: error instanceof Error ? error : new Error('Login redirect failed'),
      }));
      throw error;
    }
  }, []);

  // Logout
  const logout = useCallback(async () => {
    const msal = getMsalInstance();
    if (!msal) return;

    try {
      await msal.logoutPopup();
      setState({
        user: null,
        isLoading: false,
        isAuthenticated: false,
        error: null,
        isConfigured: true,
      });
    } catch (error) {
      console.error('Logout error:', error);
      // Force local logout even if server logout fails
      msal.clearCache();
      setState({
        user: null,
        isLoading: false,
        isAuthenticated: false,
        error: null,
        isConfigured: true,
      });
    }
  }, []);

  // Get access token for API calls
  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const msal = getMsalInstance();
    if (!msal || !state.user?.account) return null;

    try {
      // Try silent token acquisition first
      const response = await msal.acquireTokenSilent({
        ...apiRequest,
        account: state.user.account,
      });
      return response.accessToken;
    } catch (error) {
      if (error instanceof InteractionRequiredAuthError) {
        // Token expired or consent required - use popup
        try {
          const response = await msal.acquireTokenPopup(apiRequest);
          return response.accessToken;
        } catch (popupError) {
          console.error('Token acquisition failed:', popupError);
          return null;
        }
      }
      console.error('Silent token acquisition failed:', error);
      return null;
    }
  }, [state.user?.account]);

  // Role checking
  const hasRole = useCallback((role: AppRole): boolean => {
    return state.user?.roles.includes(role) ?? false;
  }, [state.user?.roles]);

  const hasAnyRole = useCallback((roles: AppRole[]): boolean => {
    return roles.some(role => state.user?.roles.includes(role));
  }, [state.user?.roles]);

  const value: AuthContextValue = {
    ...state,
    login,
    loginRedirect,
    logout,
    getAccessToken,
    hasRole,
    hasAnyRole,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

// =============================================================================
// HOOKS
// =============================================================================

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

/**
 * Hook for checking if user has required role.
 * Returns loading state while checking.
 */
export function useRequireAuth(requiredRoles?: AppRole[]): {
  isAuthorized: boolean;
  isLoading: boolean;
  user: AuthUser | null;
} {
  const { user, isLoading, isAuthenticated, hasAnyRole } = useAuth();

  if (isLoading) {
    return { isAuthorized: false, isLoading: true, user: null };
  }

  if (!isAuthenticated || !user) {
    return { isAuthorized: false, isLoading: false, user: null };
  }

  if (requiredRoles && requiredRoles.length > 0) {
    const isAuthorized = hasAnyRole(requiredRoles);
    return { isAuthorized, isLoading: false, user };
  }

  return { isAuthorized: true, isLoading: false, user };
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Parse MSAL AccountInfo to AuthUser.
 */
function parseAccountToUser(account: AccountInfo): AuthUser {
  // Extract roles from ID token claims
  const idTokenClaims = account.idTokenClaims as Record<string, unknown> | undefined;
  const roles = (idTokenClaims?.roles as string[]) || [];

  // Map to AppRole type (only include valid roles)
  const validRoles = Object.values(AppRoles);
  const appRoles = roles.filter((r): r is AppRole =>
    validRoles.includes(r as AppRole)
  );

  return {
    id: account.localAccountId,
    email: account.username,
    name: account.name || account.username,
    firstName: idTokenClaims?.given_name as string | undefined,
    lastName: idTokenClaims?.family_name as string | undefined,
    tenantId: account.tenantId,
    roles: appRoles,
    account,
  };
}

// =============================================================================
// EXPORTS
// =============================================================================

export { AppRoles, type AppRole };
