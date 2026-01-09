// =============================================================================
// SOLVEREIGN Header Component
// =============================================================================
// Top header bar with site selector, search, and user actions.
// =============================================================================

'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  Search,
  Bell,
  HelpCircle,
  LogOut,
  User,
  ChevronDown,
  Menu,
} from 'lucide-react';
import { SiteSelector } from './site-selector';
import { useTenant } from '@/lib/hooks/use-tenant';
import { cn } from '@/lib/utils';

interface HeaderProps {
  onMenuClick?: () => void;
  className?: string;
}

export function Header({ onMenuClick, className }: HeaderProps) {
  const { user, tenant } = useTenant();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);

  return (
    <header
      className={cn(
        'flex items-center justify-between px-4 h-[var(--sv-header-height)]',
        'bg-[var(--card)] border-b border-[var(--border)]',
        className
      )}
    >
      {/* Left Section */}
      <div className="flex items-center gap-4">
        {/* Mobile Menu Button */}
        <button
          type="button"
          onClick={onMenuClick}
          className="lg:hidden p-2 rounded-md hover:bg-[var(--muted)] transition-colors"
          aria-label="Menü öffnen"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Site Selector */}
        <SiteSelector />

        {/* Search */}
        <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-[var(--muted)] rounded-md w-[280px]">
          <Search className="h-4 w-4 text-[var(--muted-foreground)]" />
          <input
            type="text"
            placeholder="Suchen... (⌘K)"
            className="flex-1 bg-transparent text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:outline-none"
          />
          <kbd className="hidden lg:inline-flex items-center gap-1 px-1.5 py-0.5 text-xs text-[var(--muted-foreground)] bg-[var(--background)] rounded border border-[var(--border)]">
            ⌘K
          </kbd>
        </div>
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-2">
        {/* Help */}
        <button
          type="button"
          className="p-2 rounded-md text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
          aria-label="Hilfe"
        >
          <HelpCircle className="h-5 w-5" />
        </button>

        {/* Notifications */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowNotifications(!showNotifications)}
            className="p-2 rounded-md text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors relative"
            aria-label="Benachrichtigungen"
          >
            <Bell className="h-5 w-5" />
            {/* Notification Badge */}
            <span className="absolute top-1 right-1 h-2 w-2 bg-[var(--sv-error)] rounded-full" />
          </button>

          {/* Notifications Dropdown */}
          {showNotifications && (
            <div className="absolute right-0 mt-2 w-80 bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-[var(--sv-shadow-lg)] z-50">
              <div className="px-4 py-3 border-b border-[var(--border)]">
                <h3 className="font-medium text-sm">Benachrichtigungen</h3>
              </div>
              <div className="max-h-[300px] overflow-y-auto">
                <NotificationItem
                  title="Plan freigegeben"
                  description="KW02-2026 wurde von Max Müller freigegeben"
                  time="vor 5 Min"
                  type="success"
                />
                <NotificationItem
                  title="Audit fehlgeschlagen"
                  description="Rest-Check für KW03-2026 verletzt"
                  time="vor 1 Std"
                  type="error"
                />
                <NotificationItem
                  title="Neues Szenario"
                  description="Import von forecast_kw04.csv abgeschlossen"
                  time="vor 2 Std"
                  type="info"
                />
              </div>
              <div className="px-4 py-2 border-t border-[var(--border)]">
                <Link
                  href="/notifications"
                  className="text-sm text-[var(--sv-primary)] hover:underline"
                >
                  Alle anzeigen
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* User Menu */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-2 p-1.5 rounded-md hover:bg-[var(--muted)] transition-colors"
            aria-label="Benutzermenü"
          >
            <div className="h-8 w-8 rounded-full bg-[var(--sv-primary)] flex items-center justify-center">
              <span className="text-white text-sm font-medium">
                {user?.name?.charAt(0).toUpperCase() || 'U'}
              </span>
            </div>
            <ChevronDown className="h-4 w-4 text-[var(--muted-foreground)]" />
          </button>

          {/* User Menu Dropdown */}
          {showUserMenu && (
            <div className="absolute right-0 mt-2 w-56 bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-[var(--sv-shadow-lg)] z-50">
              {/* User Info */}
              <div className="px-4 py-3 border-b border-[var(--border)]">
                <p className="text-sm font-medium text-[var(--foreground)]">
                  {user?.name}
                </p>
                <p className="text-xs text-[var(--muted-foreground)]">
                  {user?.email}
                </p>
                <span className="inline-block mt-1 px-2 py-0.5 text-xs bg-[var(--sv-primary)]/10 text-[var(--sv-primary)] rounded">
                  {user?.role}
                </span>
              </div>

              {/* Menu Items */}
              <div className="py-1">
                <Link
                  href="/settings/profile"
                  className="flex items-center gap-3 px-4 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--muted)]"
                >
                  <User className="h-4 w-4" />
                  Profil
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    // Handle logout
                    window.location.href = '/logout';
                  }}
                  className="w-full flex items-center gap-3 px-4 py-2 text-sm text-[var(--sv-error)] hover:bg-[var(--muted)]"
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

// =============================================================================
// NOTIFICATION ITEM
// =============================================================================

interface NotificationItemProps {
  title: string;
  description: string;
  time: string;
  type: 'success' | 'error' | 'warning' | 'info';
}

function NotificationItem({ title, description, time, type }: NotificationItemProps) {
  const colors = {
    success: 'bg-[var(--sv-success)]',
    error: 'bg-[var(--sv-error)]',
    warning: 'bg-[var(--sv-warning)]',
    info: 'bg-[var(--sv-info)]',
  };

  return (
    <div className="flex gap-3 px-4 py-3 hover:bg-[var(--muted)] cursor-pointer">
      <div className={cn('h-2 w-2 mt-2 rounded-full flex-shrink-0', colors[type])} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--foreground)] truncate">
          {title}
        </p>
        <p className="text-xs text-[var(--muted-foreground)] truncate">
          {description}
        </p>
        <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
          {time}
        </p>
      </div>
    </div>
  );
}
