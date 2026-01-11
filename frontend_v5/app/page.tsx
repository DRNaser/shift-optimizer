// =============================================================================
// SOLVEREIGN Root Page - Redirect to Platform Home
// =============================================================================
// Root page redirects to platform home for authenticated users,
// or to login for unauthenticated users.
// =============================================================================

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

// Internal RBAC cookie names
// Production: __Host-sv_platform_session (requires HTTPS)
// Development: sv_platform_session (works on HTTP localhost)
const SESSION_COOKIE_NAMES = ['__Host-sv_platform_session', 'sv_platform_session'];

export default async function RootPage() {
  // Check if user is authenticated
  const cookieStore = await cookies();
  // Check both cookie names (prod and dev)
  const sessionToken = SESSION_COOKIE_NAMES
    .map(name => cookieStore.get(name)?.value)
    .find(v => v && v.length > 0);
  const isAuthenticated = Boolean(sessionToken);

  if (isAuthenticated) {
    // Redirect authenticated users to platform home
    redirect('/platform/home');
  } else {
    // Redirect unauthenticated users to login
    redirect('/platform/login');
  }
}
