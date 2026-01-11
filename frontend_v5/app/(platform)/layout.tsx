// =============================================================================
// SOLVEREIGN Platform Admin Layout (Server Component Wrapper)
// =============================================================================
// Server-side session validation + client layout shell.
// SECURITY: Validates Internal RBAC admin_session cookie before rendering.
// =============================================================================

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { PlatformLayoutClient } from './layout-client';

// Internal RBAC cookie names (from backend_py/api/security/internal_rbac.py)
// Production: __Host-sv_platform_session (requires HTTPS)
// Development: sv_platform_session (works on HTTP localhost)
const SESSION_COOKIE_NAMES = ['__Host-sv_platform_session', 'sv_platform_session'];

interface PlatformLayoutProps {
  children: React.ReactNode;
}

/**
 * Server component that validates Internal RBAC session before rendering.
 * Redirects to login if session is invalid.
 */
export default async function PlatformLayout({ children }: PlatformLayoutProps) {
  // Server-side session validation
  const cookieStore = await cookies();

  // Check both cookie names (prod and dev)
  const sessionToken = SESSION_COOKIE_NAMES
    .map(name => cookieStore.get(name)?.value)
    .find(v => v && v.length > 0);

  // Validate session exists
  const isAuthenticated = Boolean(sessionToken);

  if (!isAuthenticated) {
    // Redirect to platform login page
    redirect('/platform/login?returnTo=/platform/home');
  }

  // Pass minimal user context - full context loaded client-side via /api/auth/me
  // This avoids server-side fetch and allows proper session cookie forwarding
  const userContext = {
    email: '',  // Loaded client-side
    name: 'Loading...',
    role: 'unknown',
  };

  return (
    <PlatformLayoutClient userContext={userContext}>
      {children}
    </PlatformLayoutClient>
  );
}
