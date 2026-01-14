// =============================================================================
// SOLVEREIGN Packs Layout (Server Component Wrapper)
// =============================================================================
// Layout for pack-specific pages (roster, routing, etc).
// Validates Internal RBAC session before rendering.
// V4.6: Includes context gate for platform admins.
// =============================================================================

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { PacksLayoutClient } from './layout-client';

// Internal RBAC cookie names (from backend_py/api/security/internal_rbac.py)
// Production: __Host-sv_platform_session (requires HTTPS)
// Development: sv_platform_session (works on HTTP localhost)
const SESSION_COOKIE_NAMES = ['__Host-sv_platform_session', 'sv_platform_session'];

interface PacksLayoutProps {
  children: React.ReactNode;
}

/**
 * Server component that validates Internal RBAC session for pack pages.
 * Redirects to login if session is invalid.
 * V4.6: Wraps with client component for platform admin context checking.
 */
export default async function PacksLayout({ children }: PacksLayoutProps) {
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

  // V4.6: Wrap with client component for context gate
  // PacksLayoutClient checks if platform admin has set active context
  return <PacksLayoutClient>{children}</PacksLayoutClient>;
}
