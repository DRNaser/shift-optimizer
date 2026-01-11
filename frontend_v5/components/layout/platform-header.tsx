// =============================================================================
// SOLVEREIGN Platform Admin Header (V4.6)
// =============================================================================
// Header bar for platform-level admin console.
// V4.6: Includes context switcher for platform admins.
// =============================================================================

'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  Search,
  Bell,
  LogOut,
  User,
  ChevronDown,
  Menu,
  AlertTriangle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePlatformUser } from '@/app/(platform)/layout-client';
import { ContextSwitcher } from './context-switcher';

interface PlatformHeaderProps {
  onMenuClick?: () => void;
  className?: string;
}

export function PlatformHeader({ onMenuClick, className }: PlatformHeaderProps) {
  const [showUserMenu, setShowUserMenu] = useState(false);
  const user = usePlatformUser();

  return (
    <header
      className={cn(
        'flex items-center justify-between px-4 h-[var(--sv-header-height)]',
        'bg-[var(--sv-gray-900)] border-b border-[var(--sv-gray-700)]',
        className
      )}
    >
      {/* Left Section */}
      <div className="flex items-center gap-4">
        {/* Mobile Menu Button */}
        <button
          type="button"
          onClick={onMenuClick}
          className="lg:hidden p-2 rounded-md text-[var(--sv-gray-400)] hover:text-white hover:bg-[var(--sv-gray-800)] transition-colors"
          aria-label="Menü öffnen"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* V4.6: Context Switcher for platform admins, static badge for others */}
        {user.is_platform_admin ? (
          <ContextSwitcher
            activeTenantId={user.active_tenant_id}
            activeSiteId={user.active_site_id}
            activeTenantName={user.active_tenant_name}
            activeSiteName={user.active_site_name}
            onContextChange={user.refetchUser}
          />
        ) : (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--sv-primary)]/20 border border-[var(--sv-primary)]/30 rounded-md">
            <AlertTriangle className="h-4 w-4 text-[var(--sv-primary)]" />
            <span className="text-sm font-medium text-[var(--sv-primary)]">
              {user.role || 'User'}
            </span>
          </div>
        )}

        {/* Search */}
        <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-[var(--sv-gray-800)] rounded-md w-[280px]">
          <Search className="h-4 w-4 text-[var(--sv-gray-400)]" />
          <input
            type="text"
            placeholder="Tenant suchen..."
            className="flex-1 bg-transparent text-sm text-white placeholder:text-[var(--sv-gray-500)] focus:outline-none"
          />
        </div>
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-2">
        {/* System Status */}
        <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-[var(--sv-gray-800)] rounded-md">
          <div className="h-2 w-2 rounded-full bg-[var(--sv-success)]" />
          <span className="text-xs text-[var(--sv-gray-400)]">All systems operational</span>
        </div>

        {/* Notifications */}
        <button
          type="button"
          className="p-2 rounded-md text-[var(--sv-gray-400)] hover:text-white hover:bg-[var(--sv-gray-800)] transition-colors relative"
          aria-label="Benachrichtigungen"
        >
          <Bell className="h-5 w-5" />
          <span className="absolute top-1 right-1 h-2 w-2 bg-[var(--sv-error)] rounded-full" />
        </button>

        {/* User Menu */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-2 p-1.5 rounded-md hover:bg-[var(--sv-gray-800)] transition-colors"
            aria-label="Benutzermenü"
          >
            <div className="h-8 w-8 rounded-full bg-[var(--sv-error)] flex items-center justify-center">
              <span className="text-white text-sm font-medium">PA</span>
            </div>
            <ChevronDown className="h-4 w-4 text-[var(--sv-gray-400)]" />
          </button>

          {/* User Menu Dropdown */}
          {showUserMenu && (
            <div className="absolute right-0 mt-2 w-56 bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)] rounded-lg shadow-lg z-50">
              <div className="px-4 py-3 border-b border-[var(--sv-gray-700)]">
                <p className="text-sm font-medium text-white">Platform Admin</p>
                <p className="text-xs text-[var(--sv-gray-400)]">admin@solvereign.io</p>
              </div>
              <div className="py-1">
                <Link
                  href="/platform/settings/profile"
                  className="flex items-center gap-3 px-4 py-2 text-sm text-[var(--sv-gray-300)] hover:bg-[var(--sv-gray-700)]"
                >
                  <User className="h-4 w-4" />
                  Profil
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    window.location.href = '/logout';
                  }}
                  className="w-full flex items-center gap-3 px-4 py-2 text-sm text-[var(--sv-error)] hover:bg-[var(--sv-gray-700)]"
                >
                  <LogOut className="h-4 w-4" />
                  Abmelden
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
