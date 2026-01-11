// =============================================================================
// SOLVEREIGN Platform Admin Layout (Client Component)
// =============================================================================
// Layout shell for platform-level admin pages.
// Dark theme, tenant-agnostic administration.
// Fetches user context from Internal RBAC via /api/auth/me
// =============================================================================

'use client';

import { useState, useEffect, createContext, useContext, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { PlatformSidebar } from '@/components/layout/platform-sidebar';
import { PlatformHeader } from '@/components/layout/platform-header';

// =============================================================================
// USER CONTEXT (V4.7 - Extended with enabled_packs for dynamic nav)
// =============================================================================

interface EnabledPacks {
  roster: boolean;
  routing: boolean;
  masterdata: boolean;
  portal: boolean;
}

interface PlatformUserContext {
  email: string;
  name: string;
  role: string;
  tenant_id?: number;
  site_id?: number;
  permissions?: string[];
  isLoading: boolean;
  // V4.6: Platform admin context switching
  is_platform_admin: boolean;
  active_tenant_id?: number;
  active_site_id?: number;
  active_tenant_name?: string;
  active_site_name?: string;
  // V4.7: Enabled packs for dynamic nav
  enabled_packs: EnabledPacks;
  hasActiveContext: boolean;  // Convenience flag
  // Context methods
  refetchUser: () => Promise<void>;
  setContext: (tenantId: number, siteId?: number) => Promise<boolean>;
  clearContext: () => Promise<boolean>;
}

const PlatformUserContext = createContext<PlatformUserContext | null>(null);

export function usePlatformUser() {
  const context = useContext(PlatformUserContext);
  if (!context) {
    throw new Error('usePlatformUser must be used within PlatformLayoutClient');
  }
  return context;
}

// =============================================================================
// LAYOUT COMPONENT
// =============================================================================

interface PlatformLayoutClientProps {
  children: React.ReactNode;
  userContext: { email: string; name: string; role: string };
}

export function PlatformLayoutClient({ children, userContext: initialContext }: PlatformLayoutClientProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const router = useRouter();

  // V4.6: Create stable context method references
  const setContext = useCallback(async (tenantId: number, siteId?: number): Promise<boolean> => {
    try {
      const res = await fetch('/api/platform-admin/context', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId, site_id: siteId }),
      });
      if (res.ok) {
        // Refetch user to get updated context
        await refetchUser();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, []);

  const clearContext = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch('/api/platform-admin/context', {
        method: 'DELETE',
        credentials: 'include',
      });
      if (res.ok || res.status === 204) {
        await refetchUser();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, []);

  const [user, setUser] = useState<PlatformUserContext>({
    ...initialContext,
    isLoading: true,
    is_platform_admin: false,
    enabled_packs: { roster: false, routing: false, masterdata: false, portal: false },
    hasActiveContext: false,
    refetchUser: async () => {},
    setContext,
    clearContext,
  });

  // V4.6: Refetch user context (exposed via context)
  const refetchUser = useCallback(async () => {
    try {
      const response = await fetch('/api/auth/me', {
        credentials: 'include',
        cache: 'no-store',
      });

      if (response.status === 401) {
        router.push('/platform/login?returnTo=/platform/home');
        return;
      }

      if (!response.ok) {
        console.error('Failed to fetch user context:', response.status);
        return;
      }

      const data = await response.json();

      if (data.success && data.user) {
        const u = data.user;
        const isPlatformAdmin = u.is_platform_admin || u.role_name === 'platform_admin';
        // Determine if user has active tenant context
        const hasContext = isPlatformAdmin
          ? Boolean(u.active_tenant_id)
          : Boolean(u.tenant_id);

        setUser(prev => ({
          ...prev,
          email: u.email || '',
          name: u.display_name || u.email || 'Unknown',
          role: u.role_name || u.role || 'unknown',
          tenant_id: u.tenant_id,
          site_id: u.site_id,
          permissions: u.permissions || [],
          isLoading: false,
          // V4.6: Platform admin context fields
          is_platform_admin: isPlatformAdmin,
          active_tenant_id: u.active_tenant_id,
          active_site_id: u.active_site_id,
          active_tenant_name: u.active_tenant_name,
          active_site_name: u.active_site_name,
          // V4.7: Enabled packs for dynamic nav
          enabled_packs: u.enabled_packs || { roster: false, routing: false, masterdata: false, portal: false },
          hasActiveContext: hasContext,
        }));
      } else {
        router.push('/platform/login?returnTo=/platform/home');
      }
    } catch (error) {
      console.error('Error fetching user context:', error);
    }
  }, [router]);

  // Fetch full user context from Internal RBAC on mount
  useEffect(() => {
    refetchUser();
  }, [refetchUser]);

  // V4.6: Update context methods when refetchUser changes
  useEffect(() => {
    setUser(prev => ({
      ...prev,
      refetchUser,
      setContext,
      clearContext,
    }));
  }, [refetchUser, setContext, clearContext]);

  return (
    <PlatformUserContext.Provider value={user}>
      <div className="flex h-screen bg-[var(--sv-gray-900)]">
        {/* Sidebar - Desktop */}
        <div className="hidden lg:block">
          <PlatformSidebar />
        </div>

        {/* Sidebar - Mobile Overlay */}
        {sidebarOpen && (
          <>
            {/* Backdrop */}
            <div
              className="fixed inset-0 bg-black/50 z-40 lg:hidden"
              onClick={() => setSidebarOpen(false)}
            />
            {/* Sidebar */}
            <div className="fixed inset-y-0 left-0 z-50 lg:hidden">
              <PlatformSidebar />
            </div>
          </>
        )}

        {/* Main Content Area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <PlatformHeader onMenuClick={() => setSidebarOpen(true)} />

          {/* Page Content */}
          <main className="flex-1 overflow-y-auto bg-[var(--sv-gray-800)]">
            <div className="max-w-[var(--sv-content-max-width)] mx-auto p-6">
              {children}
            </div>
          </main>
        </div>
      </div>
    </PlatformUserContext.Provider>
  );
}
