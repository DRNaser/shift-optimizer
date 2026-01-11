// =============================================================================
// SOLVEREIGN Packs Layout (URL: /packs/*)
// =============================================================================
// Server-side session validation + client-side context gate for pack routes.
// V4.7: Implements strict context gate - platform_admin must have active context.
// =============================================================================

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { PacksContextGate } from './context-gate';

// Internal RBAC cookie name (CANONICAL: __Host-sv_platform_session)
const ADMIN_SESSION_COOKIE = '__Host-sv_platform_session';

interface PacksLayoutProps {
  children: React.ReactNode;
}

export default async function PacksLayout({ children }: PacksLayoutProps) {
  // Server-side session validation
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get(ADMIN_SESSION_COOKIE)?.value;
  const isAuthenticated = Boolean(sessionToken && sessionToken.length > 0);

  if (!isAuthenticated) {
    redirect('/platform/login?returnTo=/platform/home');
  }

  // V4.7: Wrap with context gate to enforce tenant context
  return <PacksContextGate>{children}</PacksContextGate>;
}
