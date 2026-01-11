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

// Internal RBAC cookie name (CANONICAL: __Host-sv_platform_session)
const ADMIN_SESSION_COOKIE = '__Host-sv_platform_session';

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

  // Check for Internal RBAC admin_session cookie
  const sessionToken = cookieStore.get(ADMIN_SESSION_COOKIE)?.value;

  // Validate session exists
  const isAuthenticated = Boolean(sessionToken && sessionToken.length > 0);

  if (!isAuthenticated) {
    // Redirect to platform login page
    redirect('/platform/login?returnTo=/platform/home');
  }

  // V4.6: Wrap with client component for context gate
  // PacksLayoutClient checks if platform admin has set active context
  return <PacksLayoutClient>{children}</PacksLayoutClient>;
}
