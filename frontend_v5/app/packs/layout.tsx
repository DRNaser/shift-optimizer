// =============================================================================
// SOLVEREIGN Packs Layout (URL: /packs/*)
// =============================================================================
// Server-side session validation + client-side context gate for pack routes.
// V4.7: Implements strict context gate - platform_admin must have active context.
// =============================================================================

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { PacksContextGate } from './context-gate';

// Internal RBAC cookie names (from backend_py/api/security/internal_rbac.py)
// Production: __Host-sv_platform_session (requires HTTPS)
// Development: sv_platform_session (works on HTTP localhost)
const SESSION_COOKIE_NAMES = ['__Host-sv_platform_session', 'sv_platform_session'];

interface PacksLayoutProps {
  children: React.ReactNode;
}

export default async function PacksLayout({ children }: PacksLayoutProps) {
  // Server-side session validation
  const cookieStore = await cookies();

  // Check both cookie names (prod and dev)
  const sessionToken = SESSION_COOKIE_NAMES
    .map(name => cookieStore.get(name)?.value)
    .find(v => v && v.length > 0);

  const isAuthenticated = Boolean(sessionToken);

  if (!isAuthenticated) {
    redirect('/platform/login?returnTo=/platform/home');
  }

  // V4.7: Wrap with context gate to enforce tenant context
  return <PacksContextGate>{children}</PacksContextGate>;
}
