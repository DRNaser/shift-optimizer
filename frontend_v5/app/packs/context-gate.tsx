// =============================================================================
// SOLVEREIGN Packs Context Gate (V4.7)
// =============================================================================
// Client component that enforces tenant context for pack routes.
// Platform admins must select a tenant before accessing packs.
// Regular users always have context via their binding.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import { Building2, AlertTriangle, ArrowRight, Loader2 } from 'lucide-react';

interface UserContext {
  is_platform_admin: boolean;
  active_tenant_id?: number;
  active_tenant_name?: string;
  active_site_name?: string;
  tenant_id?: number;  // For regular users
  enabled_packs?: {
    roster: boolean;
    routing: boolean;
    masterdata: boolean;
    portal: boolean;
  };
}

interface PacksContextGateProps {
  children: React.ReactNode;
}

export function PacksContextGate({ children }: PacksContextGateProps) {
  const [user, setUser] = useState<UserContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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

        if (!res.ok) {
          setError('Failed to load user context');
          setLoading(false);
          return;
        }

        const data = await res.json();
        if (data.success && data.user) {
          setUser({
            is_platform_admin: data.user.is_platform_admin || data.user.role_name === 'platform_admin',
            active_tenant_id: data.user.active_tenant_id,
            active_tenant_name: data.user.active_tenant_name,
            active_site_name: data.user.active_site_name,
            tenant_id: data.user.tenant_id,
            enabled_packs: data.user.enabled_packs,
          });
        } else {
          router.push(`/platform/login?returnTo=${encodeURIComponent(pathname)}`);
          return;
        }
      } catch (err) {
        console.error('Failed to fetch user context:', err);
        setError('Network error');
      } finally {
        setLoading(false);
      }
    }
    fetchUser();
  }, [router, pathname]);

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 text-slate-400 animate-spin" />
          <p className="text-slate-400">Loading...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center p-8">
        <div className="max-w-md w-full text-center">
          <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-red-500/20 mb-4">
            <AlertTriangle className="h-8 w-8 text-red-400" />
          </div>
          <h2 className="text-xl font-bold text-white mb-2">Error</h2>
          <p className="text-slate-400 mb-6">{error}</p>
          <Link
            href="/platform/home"
            className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 text-white rounded-md hover:bg-slate-700 transition-colors"
          >
            <ArrowRight className="h-4 w-4 rotate-180" />
            Back to Home
          </Link>
        </div>
      </div>
    );
  }

  // Check if platform admin needs context
  if (user?.is_platform_admin && !user.active_tenant_id) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center p-8">
        <div className="max-w-md w-full bg-slate-800 border border-slate-700 rounded-lg p-6 text-center">
          <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-amber-500/20 mb-4">
            <AlertTriangle className="h-8 w-8 text-amber-400" />
          </div>
          <h2 className="text-xl font-bold text-white mb-2">Context Required</h2>
          <p className="text-slate-400 mb-6">
            As a platform admin, you need to select a tenant context before accessing pack features.
          </p>
          <Link
            href={`/select-tenant?returnTo=${encodeURIComponent(pathname)}`}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-emerald-600 text-white rounded-md hover:bg-emerald-500 transition-colors"
          >
            <Building2 className="h-5 w-5" />
            Select Tenant
          </Link>
          <div className="mt-4">
            <Link
              href="/platform/home"
              className="text-sm text-slate-400 hover:text-white transition-colors"
            >
              ← Back to Platform Home
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Check if pack is enabled (extract pack name from pathname)
  const packMatch = pathname.match(/^\/packs\/(\w+)/);
  if (packMatch && user?.enabled_packs) {
    const packName = packMatch[1] as keyof typeof user.enabled_packs;
    if (packName in user.enabled_packs && !user.enabled_packs[packName]) {
      return (
        <div className="min-h-screen bg-slate-900 flex items-center justify-center p-8">
          <div className="max-w-md w-full bg-slate-800 border border-slate-700 rounded-lg p-6 text-center">
            <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-slate-600/20 mb-4">
              <AlertTriangle className="h-8 w-8 text-slate-400" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Pack Not Available</h2>
            <p className="text-slate-400 mb-6">
              The <strong className="text-white capitalize">{packName}</strong> pack is not enabled for this tenant.
              Contact your administrator to enable it.
            </p>
            <Link
              href="/platform/home"
              className="inline-flex items-center gap-2 px-4 py-2 bg-slate-700 text-white rounded-md hover:bg-slate-600 transition-colors"
            >
              <ArrowRight className="h-4 w-4 rotate-180" />
              Back to Home
            </Link>
          </div>
        </div>
      );
    }
  }

  // Context banner for platform admins
  if (user?.is_platform_admin && user.active_tenant_id) {
    return (
      <div className="min-h-screen bg-slate-900">
        {/* Context Banner */}
        <div className="bg-emerald-900/30 border-b border-emerald-800/50 px-4 py-2">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-emerald-400">
              <Building2 className="h-4 w-4" />
              <span>
                Working as <strong>{user.active_tenant_name || `Tenant ${user.active_tenant_id}`}</strong>
                {user.active_site_name && (
                  <span className="opacity-80"> / {user.active_site_name}</span>
                )}
              </span>
            </div>
            <Link
              href={`/select-tenant?returnTo=${encodeURIComponent(pathname)}`}
              className="text-xs text-emerald-400 hover:text-emerald-300 hover:underline"
            >
              Change
            </Link>
          </div>
        </div>
        {children}
      </div>
    );
  }

  // Regular users - just render children
  return <>{children}</>;
}
