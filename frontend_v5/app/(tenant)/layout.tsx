// =============================================================================
// SOLVEREIGN Tenant Console Layout
// =============================================================================
// Main layout shell for tenant-scoped pages.
// Provides sidebar navigation, header with site selector, and content area.
//
// PHASE 2 ADDITIONS:
//   - TenantStatusProvider: Provides status context for blocked/degraded handling
//   - TenantErrorProvider: Global error handling (401/403/409/503)
//   - TenantStatusBanner: Persistent banner for operational status
//   - GlobalErrorHandler: Auto-shows error modals/toasts
// =============================================================================

'use client';

import { useState } from 'react';
import { Sidebar } from '@/components/layout/sidebar';
import { Header } from '@/components/layout/header';
import { cn } from '@/lib/utils';
import { useTenant } from '@/lib/hooks/use-tenant';
import {
  TenantStatusProvider,
  TenantStatusBanner,
  useTenantStatus,
  TenantErrorProvider,
  GlobalErrorHandler,
} from '@/components/tenant';

interface TenantLayoutProps {
  children: React.ReactNode;
}

export default function TenantLayout({ children }: TenantLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { tenant, currentSite } = useTenant();

  // Get tenant/site codes for status provider
  const tenantCode = tenant?.slug || 'unknown';
  const siteCode = currentSite?.code || 'unknown';

  return (
    <TenantErrorProvider>
      <TenantStatusProvider tenantCode={tenantCode} siteCode={siteCode}>
        <TenantLayoutContent sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen}>
          {children}
        </TenantLayoutContent>
      </TenantStatusProvider>
    </TenantErrorProvider>
  );
}

// Separate component to use status hook inside provider
function TenantLayoutContent({
  children,
  sidebarOpen,
  setSidebarOpen,
}: {
  children: React.ReactNode;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}) {
  const { status, isLoading, refresh } = useTenantStatus();

  return (
    <div className="flex h-screen bg-[var(--background)]">
      {/* Sidebar - Desktop */}
      <div className="hidden lg:block">
        <Sidebar />
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
            <Sidebar />
          </div>
        </>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Status Banner (shows only if degraded/blocked) */}
        <TenantStatusBanner
          status={status}
          isLoading={isLoading}
          onRefresh={refresh}
        />

        {/* Header */}
        <Header onMenuClick={() => setSidebarOpen(true)} />

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-[var(--sv-content-max-width)] mx-auto p-6">
            {children}
          </div>
        </main>
      </div>

      {/* Global Error Handler */}
      <GlobalErrorHandler />
    </div>
  );
}
