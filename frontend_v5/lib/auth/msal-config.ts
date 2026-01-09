// =============================================================================
// SOLVEREIGN - Entra ID (Azure AD) MSAL Configuration
// =============================================================================
// Configuration for Microsoft Authentication Library (MSAL) with Entra ID.
//
// Environment variables required:
// - NEXT_PUBLIC_AZURE_AD_CLIENT_ID: Application (client) ID
// - NEXT_PUBLIC_AZURE_AD_TENANT_ID: Directory (tenant) ID
// - NEXT_PUBLIC_AZURE_AD_REDIRECT_URI: Redirect URI after auth
// =============================================================================

import type { Configuration, PopupRequest, RedirectRequest } from '@azure/msal-browser';

// =============================================================================
// ENVIRONMENT CONFIGURATION
// =============================================================================

const clientId = process.env.NEXT_PUBLIC_AZURE_AD_CLIENT_ID || '';
const tenantId = process.env.NEXT_PUBLIC_AZURE_AD_TENANT_ID || '';
const redirectUri = process.env.NEXT_PUBLIC_AZURE_AD_REDIRECT_URI || (
  typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000'
);

// API scope for backend access
const apiScope = process.env.NEXT_PUBLIC_AZURE_AD_API_SCOPE || `api://${clientId}/access_as_user`;

// =============================================================================
// MSAL CONFIGURATION
// =============================================================================

export const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri,
    postLogoutRedirectUri: redirectUri,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: 'localStorage', // Required for SSO across tabs
    storeAuthStateInCookie: true, // Required for IE11/Edge
  },
  system: {
    loggerOptions: {
      logLevel: 3, // Info
      piiLoggingEnabled: false,
    },
  },
};

// =============================================================================
// AUTHENTICATION REQUEST CONFIGURATIONS
// =============================================================================

/**
 * Scopes for login request.
 * - openid: Required for OIDC
 * - profile: User's basic profile info
 * - email: User's email address
 * - offline_access: Refresh tokens
 */
export const loginRequest: PopupRequest = {
  scopes: ['openid', 'profile', 'email', 'offline_access'],
};

/**
 * Scopes for API access.
 * These scopes are used when calling the SOLVEREIGN backend API.
 */
export const apiRequest: PopupRequest = {
  scopes: [apiScope],
};

/**
 * Silent request for token acquisition.
 */
export const silentRequest: PopupRequest = {
  scopes: ['openid', 'profile', 'email', apiScope],
};

// =============================================================================
// APP ROLES (from Entra ID App Registration)
// =============================================================================

/**
 * Application roles defined in Entra ID.
 * These are assigned to users/groups in the Azure portal.
 */
export const AppRoles = {
  /** Platform administrator - full access */
  PLATFORM_ADMIN: 'Platform.Admin',
  /** Tenant administrator - manage own tenant */
  TENANT_ADMIN: 'Tenant.Admin',
  /** Approver - can approve/publish plans */
  APPROVER: 'Approver',
  /** Viewer - read-only access */
  VIEWER: 'Viewer',
  /** Dispatcher - operational access */
  DISPATCHER: 'Dispatcher',
} as const;

export type AppRole = typeof AppRoles[keyof typeof AppRoles];

// =============================================================================
// VALIDATION
// =============================================================================

/**
 * Check if MSAL is properly configured.
 */
export function isMsalConfigured(): boolean {
  return Boolean(clientId && tenantId);
}

/**
 * Get configuration status for debugging.
 */
export function getMsalConfigStatus(): {
  configured: boolean;
  clientId: string;
  tenantId: string;
  redirectUri: string;
} {
  return {
    configured: isMsalConfigured(),
    clientId: clientId ? `${clientId.substring(0, 8)}...` : '(not set)',
    tenantId: tenantId ? `${tenantId.substring(0, 8)}...` : '(not set)',
    redirectUri,
  };
}
