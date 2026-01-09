// =============================================================================
// SOLVEREIGN Platform Admin Layout (Server Component Wrapper)
// =============================================================================
// Server-side session validation + client layout shell.
// SECURITY: Validates platform session before rendering.
// =============================================================================

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { PlatformLayoutClient } from './layout-client';
import { PLATFORM_COOKIE_NAMES } from '@/lib/platform-rbac';

interface PlatformLayoutProps {
  children: React.ReactNode;
}

/**
 * Server component that validates platform session before rendering.
 * Redirects to login if session is invalid.
 */
export default async function PlatformLayout({ children }: PlatformLayoutProps) {
  // Server-side session validation
  const cookieStore = await cookies();

  // Try __Host- prefixed cookie first, fallback to old name for migration
  const sessionToken =
    cookieStore.get(PLATFORM_COOKIE_NAMES.session)?.value ||
    cookieStore.get('sv_platform_session')?.value;
  const userEmail = cookieStore.get(PLATFORM_COOKIE_NAMES.userEmail)?.value;

  // Validate session exists
  // TODO: In production, validate against session store / Entra ID
  const isAuthenticated = Boolean(sessionToken && sessionToken.length > 0);

  if (!isAuthenticated) {
    // Redirect to platform login page
    // Using a query param to return after login
    redirect('/platform/login?returnTo=/platform/orgs');
  }

  // Pass user context to client layout
  const userContext = {
    email: userEmail || '',
    name: cookieStore.get(PLATFORM_COOKIE_NAMES.userName)?.value || 'Platform User',
    role: cookieStore.get(PLATFORM_COOKIE_NAMES.role)?.value || 'platform_viewer',
  };

  return (
    <PlatformLayoutClient userContext={userContext}>
      {children}
    </PlatformLayoutClient>
  );
}
