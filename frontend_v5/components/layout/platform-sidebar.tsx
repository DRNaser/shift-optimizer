// =============================================================================
// SOLVEREIGN Platform Admin Sidebar (V4.7)
// =============================================================================
// Navigation sidebar for platform-level admin console.
// V4.7: Dynamic pack rendering based on tenant capabilities.
// Packs only visible when hasActiveContext AND pack is enabled.
// =============================================================================

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Building2,
  AlertTriangle,
  Play,
  Home,
  Users,
  Calendar,
  Truck,
  FileText,
  Settings,
  LogOut,
  Shield,
  Key,
  UserCog,
  Activity,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePlatformUser } from '@/app/(platform)/layout-client';

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  requiresContext?: boolean;  // Requires active tenant context
  packKey?: 'roster' | 'routing' | 'masterdata' | 'portal';  // Which pack controls visibility
}

interface NavSection {
  title: string;
  items: NavItem[];
  platformAdminOnly?: boolean;  // Only visible to platform_admin role
}

// Platform navigation (always visible)
const PLATFORM_ITEMS: NavItem[] = [
  { label: 'Home', href: '/platform/home', icon: Home },
  { label: 'Portal Admin', href: '/portal-admin/dashboard', icon: Users, requiresContext: true, packKey: 'portal' },
  { label: 'Organizations', href: '/orgs', icon: Building2 },
  { label: 'Solver Runs', href: '/runs', icon: Play, requiresContext: true },
  { label: 'Escalations', href: '/escalations', icon: AlertTriangle },
];

// Pack navigation (requires context AND pack enabled)
const PACK_ITEMS: NavItem[] = [
  { label: 'Roster Workbench', href: '/packs/roster/workbench', icon: Calendar, packKey: 'roster', badge: 'Pack' },
  { label: 'Routing', href: '/packs/routing', icon: Truck, packKey: 'routing', badge: 'Pack' },
  { label: 'Master Data', href: '/packs/masterdata', icon: FileText, packKey: 'masterdata', badge: 'Pack' },
];

// Admin navigation (platform_admin only)
const ADMIN_ITEMS: NavItem[] = [
  { label: 'Users', href: '/platform-admin/users', icon: UserCog },
  { label: 'Roles', href: '/platform-admin/roles', icon: Shield },
  { label: 'Permissions', href: '/platform-admin/permissions', icon: Key },
  { label: 'Sessions', href: '/platform-admin/sessions', icon: Activity },
  { label: 'Tenants', href: '/platform-admin/tenants', icon: Building2 },
];

interface PlatformSidebarProps {
  className?: string;
}

export function PlatformSidebar({ className }: PlatformSidebarProps) {
  const pathname = usePathname();
  const user = usePlatformUser();

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'include',
      });
      window.location.href = '/platform/login';
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  // Filter items based on context and enabled packs
  const filterItems = (items: NavItem[]): NavItem[] => {
    return items.filter(item => {
      // If requires context, check hasActiveContext
      if (item.requiresContext && !user.hasActiveContext) {
        return false;
      }
      // If has packKey, check if that pack is enabled
      if (item.packKey && !user.enabled_packs[item.packKey]) {
        return false;
      }
      return true;
    });
  };

  // Get visible pack items (requires context + pack enabled)
  const visiblePackItems = user.hasActiveContext
    ? PACK_ITEMS.filter(item => !item.packKey || user.enabled_packs[item.packKey])
    : [];

  // Get visible platform items
  const visiblePlatformItems = filterItems(PLATFORM_ITEMS);

  // Get admin items (only for platform_admin)
  const visibleAdminItems = user.is_platform_admin ? ADMIN_ITEMS : [];

  // Render nav item
  const renderNavItem = (item: NavItem) => {
    const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
    const Icon = item.icon;

    return (
      <li key={item.href}>
        <Link
          href={item.href}
          className={cn(
            'flex items-center gap-3 px-3 py-2 rounded-md',
            'text-[var(--sv-gray-400)] hover:text-white',
            'hover:bg-[var(--sv-gray-800)] transition-colors duration-150',
            isActive && 'bg-[var(--sv-primary)] text-white'
          )}
        >
          <Icon className="h-4 w-4" />
          <span className="text-sm">{item.label}</span>
          {item.badge && (
            <span className="ml-auto px-1.5 py-0.5 text-[10px] bg-[var(--sv-gray-700)] text-[var(--sv-gray-400)] rounded">
              {item.badge}
            </span>
          )}
        </Link>
      </li>
    );
  };

  return (
    <aside
      className={cn(
        'flex flex-col h-full bg-[var(--sv-gray-900)] text-white',
        'w-[var(--sv-sidebar-width)]',
        className
      )}
    >
      {/* Logo Section */}
      <div className="flex items-center gap-3 px-4 h-[var(--sv-header-height)] border-b border-[var(--sv-gray-700)]">
        <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center">
          <span className="text-white font-bold text-sm">S</span>
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold">SOLVEREIGN</span>
          <span className="text-xs text-[var(--sv-gray-400)]">
            Platform v4.7
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-2">
        {/* Platform Section */}
        <div className="mb-6">
          <h3 className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--sv-gray-500)]">
            Platform
          </h3>
          <ul className="space-y-1">
            {visiblePlatformItems.map(renderNavItem)}
          </ul>
        </div>

        {/* Packs Section - Only visible with context */}
        {visiblePackItems.length > 0 && (
          <div className="mb-6">
            <h3 className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--sv-gray-500)]">
              Packs
            </h3>
            <ul className="space-y-1">
              {visiblePackItems.map(renderNavItem)}
            </ul>
          </div>
        )}

        {/* No Context Banner for platform admins */}
        {user.is_platform_admin && !user.hasActiveContext && (
          <div className="mb-6 mx-2 p-3 rounded-md bg-[var(--sv-warning)]/10 border border-[var(--sv-warning)]/30">
            <p className="text-xs text-[var(--sv-warning)] mb-2">
              Select a tenant to access Packs
            </p>
            <Link
              href="/select-tenant"
              className="text-xs text-[var(--sv-primary)] hover:underline"
            >
              Select Tenant →
            </Link>
          </div>
        )}

        {/* Admin Section - Platform admin only */}
        {visibleAdminItems.length > 0 && (
          <div className="mb-6">
            <h3 className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--sv-gray-500)]">
              Administration
            </h3>
            <ul className="space-y-1">
              {visibleAdminItems.map(renderNavItem)}
            </ul>
          </div>
        )}
      </nav>

      {/* User Section */}
      <div className="border-t border-[var(--sv-gray-700)] p-4">
        {/* Active Context Badge */}
        {user.hasActiveContext && user.active_tenant_name && (
          <div className="mb-3 p-2 rounded-md bg-[var(--sv-primary)]/10 border border-[var(--sv-primary)]/30">
            <p className="text-xs text-[var(--sv-gray-400)]">Working as</p>
            <p className="text-sm font-medium text-[var(--sv-primary)] truncate">
              {user.active_tenant_name}
              {user.active_site_name && (
                <span className="text-[var(--sv-gray-400)]"> / {user.active_site_name}</span>
              )}
            </p>
          </div>
        )}

        <div className="flex items-center gap-3 mb-3">
          <div className="h-8 w-8 rounded-full bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center">
            <span className="text-white text-xs font-medium">
              {user.name?.slice(0, 2)?.toUpperCase() || '??'}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">
              {user.isLoading ? 'Loading...' : user.name}
            </p>
            <p className="text-xs text-[var(--sv-gray-400)] truncate">
              {user.isLoading ? '' : user.role}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleLogout}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--sv-gray-400)] hover:text-white hover:bg-[var(--sv-gray-800)] rounded-md transition-colors"
        >
          <LogOut className="h-4 w-4" />
          Logout
        </button>
      </div>
    </aside>
  );
}
