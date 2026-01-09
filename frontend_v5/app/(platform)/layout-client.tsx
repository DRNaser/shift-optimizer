// =============================================================================
// SOLVEREIGN Platform Admin Layout (Client Component)
// =============================================================================
// Layout shell for platform-level admin pages.
// Dark theme, tenant-agnostic administration.
// =============================================================================

'use client';

import { useState, createContext, useContext } from 'react';
import { PlatformSidebar } from '@/components/layout/platform-sidebar';
import { PlatformHeader } from '@/components/layout/platform-header';
import { cn } from '@/lib/utils';

// =============================================================================
// USER CONTEXT
// =============================================================================

interface PlatformUserContext {
  email: string;
  name: string;
  role: string;
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
  userContext: PlatformUserContext;
}

export function PlatformLayoutClient({ children, userContext }: PlatformLayoutClientProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <PlatformUserContext.Provider value={userContext}>
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
