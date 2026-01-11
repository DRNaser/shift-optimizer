// =============================================================================
// SOLVEREIGN Platform Home Page (URL: /platform/home)
// =============================================================================
// Server component that validates auth then renders client layout + home content.
// =============================================================================

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { PlatformLayoutClient } from '../../(platform)/layout-client';
import PlatformHomeContent from './content';

// Internal RBAC cookie names
// Production: __Host-sv_platform_session (requires HTTPS)
// Development: sv_platform_session (works on HTTP localhost)
const SESSION_COOKIE_NAMES = ['__Host-sv_platform_session', 'sv_platform_session'];

export default async function PlatformHomePage() {
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

  // Pass minimal user context - full context loaded client-side via /api/auth/me
  const userContext = {
    email: '',
    name: 'Loading...',
    role: 'unknown',
  };

  return (
    <PlatformLayoutClient userContext={userContext}>
      <PlatformHomeContent />
    </PlatformLayoutClient>
  );
}
