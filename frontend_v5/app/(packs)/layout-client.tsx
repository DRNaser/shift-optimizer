// =============================================================================
// SOLVEREIGN V4.6 - Packs Layout Client (Context Gate)
// =============================================================================
// Client component that checks platform admin context.
// Redirects to tenant picker if platform admin hasn't set active context.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { Building2, AlertTriangle } from 'lucide-react';

interface UserContext {
  email: string;
  role: string;
  is_platform_admin: boolean;
  tenant_id?: number;
  active_tenant_id?: number;
  active_site_id?: number;
  active_tenant_name?: string;
  active_site_name?: string;
}

interface PacksLayoutClientProps {
  children: React.ReactNode;
}

export function PacksLayoutClient({ children }: PacksLayoutClientProps) {
  const [user, setUser] = useState<UserContext | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    async function fetchUser() {
      try {
        const res = await fetch('/api/auth/me', {
          credentials: 'include',
          cache: 'no-store',
        });

        if (res.status === 401) {
          router.push(`/platform/login?returnTo=${encodeURIComponent(pathname)}`);
          return;
        }

        if (res.ok) {
          const data = await res.json();
          if (data.success && data.user) {
            setUser({
              email: data.user.email,
              role: data.user.role,
              is_platform_admin: data.user.role === 'platform_admin',
              tenant_id: data.user.tenant_id,
              active_tenant_id: data.user.active_tenant_id,
              active_site_id: data.user.active_site_id,
              active_tenant_name: data.user.active_tenant_name,
              active_site_name: data.user.active_site_name,
            });
          }
        }
      } catch (err) {
        console.error('Failed to fetch user context:', err);
      } finally {
        setLoading(false);
      }
    }
    fetchUser();
  }, [router, pathname]);

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--sv-gray-900)] flex items-center justify-center">
        <div className="text-[var(--sv-gray-400)]">Loading...</div>
      </div>
    );
  }

  // Check if platform admin needs to select context
  if (user?.is_platform_admin && !user.active_tenant_id) {
    return (
      <div className="min-h-screen bg-[var(--sv-gray-900)] flex items-center justify-center p-8">
        <div className="max-w-md w-full bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)] rounded-lg p-6 text-center">
          <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-[var(--sv-warning)]/20 mb-4">
            <AlertTriangle className="h-8 w-8 text-[var(--sv-warning)]" />
          </div>
          <h2 className="text-xl font-bold text-white mb-2">Context Required</h2>
          <p className="text-[var(--sv-gray-400)] mb-6">
            As a platform admin, you need to select a tenant context before accessing pack features.
          </p>
          <button
            type="button"
            onClick={() => router.push(`/platform/select-tenant?returnTo=${encodeURIComponent(pathname)}`)}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary)]/80 transition-colors"
          >
            <Building2 className="h-5 w-5" />
            Select Tenant
          </button>
        </div>
      </div>
    );
  }

  // Show active context badge for platform admins
  if (user?.is_platform_admin && user.active_tenant_id) {
    return (
      <div className="min-h-screen bg-[var(--sv-gray-900)]">
        {/* Context Banner */}
        <div className="bg-[var(--sv-primary)]/10 border-b border-[var(--sv-primary)]/30 px-4 py-2">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-[var(--sv-primary)]">
              <Building2 className="h-4 w-4" />
              <span>
                Working as <strong>{user.active_tenant_name || `Tenant ${user.active_tenant_id}`}</strong>
                {user.active_site_name && (
                  <span className="opacity-80"> / {user.active_site_name}</span>
                )}
              </span>
            </div>
            <button
              type="button"
              onClick={() => router.push(`/platform/select-tenant?returnTo=${encodeURIComponent(pathname)}`)}
              className="text-xs text-[var(--sv-primary)] hover:underline"
            >
              Change
            </button>
          </div>
        </div>
        {children}
      </div>
    );
  }

  // Regular users - just render children
  return <>{children}</>;
}
