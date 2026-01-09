// =============================================================================
// SOLVEREIGN Sidebar Navigation Component
// =============================================================================
// Main navigation sidebar for tenant console.
// =============================================================================

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Calendar,
  FileText,
  Shield,
  Lock,
  MapPin,
  TrendingUp,
  Settings,
  Users,
  Building2,
  ChevronRight,
  LayoutDashboard,
} from 'lucide-react';
import { useTenant, usePacks } from '@/lib/hooks/use-tenant';
import { cn } from '@/lib/utils';
import type { PackId } from '@/lib/tenant-types';

// Icon mapping for packs
const PACK_ICONS: Record<PackId, React.ComponentType<{ className?: string }>> = {
  core: Calendar,
  routing: MapPin,
  forecasting: TrendingUp,
  compliance: Shield,
};

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string | number;
  children?: NavItem[];
}

interface SidebarProps {
  className?: string;
}

export function Sidebar({ className }: SidebarProps) {
  const { tenant, user } = useTenant();
  const { enabledPacks, hasPackAccess } = usePacks();
  const pathname = usePathname();

  // Build navigation items based on enabled packs
  const navItems: NavItem[] = [
    {
      label: 'Dashboard',
      href: '/dashboard',
      icon: LayoutDashboard,
    },
  ];

  // Core Pack Navigation
  if (hasPackAccess('core')) {
    navItems.push(
      {
        label: 'Szenarien',
        href: '/scenarios',
        icon: FileText,
      },
      {
        label: 'Pläne',
        href: '/plans',
        icon: Calendar,
      },
      {
        label: 'Audits',
        href: '/audits',
        icon: Shield,
      },
      {
        label: 'Evidence',
        href: '/evidence',
        icon: Lock,
      }
    );
  }

  // Routing Pack Navigation
  if (hasPackAccess('routing')) {
    navItems.push({
      label: 'Routing',
      href: '/routing',
      icon: MapPin,
      children: [
        { label: 'Szenarien', href: '/routing/scenarios', icon: FileText },
        { label: 'Routen', href: '/routing/routes', icon: MapPin },
        { label: 'Depots', href: '/routing/depots', icon: Building2 },
      ],
    });
  }

  // Forecasting Pack Navigation
  if (hasPackAccess('forecasting')) {
    navItems.push({
      label: 'Forecasting',
      href: '/forecasting',
      icon: TrendingUp,
      children: [
        { label: 'Prognosen', href: '/forecasting/predictions', icon: TrendingUp },
        { label: 'Kapazität', href: '/forecasting/capacity', icon: Users },
      ],
    });
  }

  return (
    <aside
      className={cn(
        'flex flex-col h-full bg-[var(--card)] border-r border-[var(--border)]',
        'w-[var(--sv-sidebar-width)]',
        className
      )}
    >
      {/* Logo Section */}
      <div className="flex items-center gap-3 px-4 h-[var(--sv-header-height)] border-b border-[var(--border)]">
        <div className="h-8 w-8 rounded-lg bg-[var(--sv-primary)] flex items-center justify-center">
          <span className="text-white font-bold text-sm">SV</span>
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-[var(--foreground)]">
            SOLVEREIGN
          </span>
          <span className="text-xs text-[var(--muted-foreground)]">
            {tenant?.name || 'Loading...'}
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-2">
        <ul className="space-y-1">
          {navItems.map((item) => (
            <NavItemComponent
              key={item.href}
              item={item}
              pathname={pathname}
            />
          ))}
        </ul>
      </nav>

      {/* Bottom Section - Settings */}
      <div className="border-t border-[var(--border)] p-2">
        <Link
          href="/settings"
          className={cn(
            'flex items-center gap-3 px-3 py-2 rounded-md',
            'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
            'hover:bg-[var(--muted)] transition-colors duration-150',
            pathname.startsWith('/settings') && 'bg-[var(--muted)] text-[var(--foreground)]'
          )}
        >
          <Settings className="h-4 w-4" />
          <span className="text-sm">Einstellungen</span>
        </Link>
      </div>

      {/* User Section */}
      <div className="border-t border-[var(--border)] p-4">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-[var(--sv-primary)] flex items-center justify-center">
            <span className="text-white text-xs font-medium">
              {user?.name?.charAt(0).toUpperCase() || 'U'}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-[var(--foreground)] truncate">
              {user?.name || 'Loading...'}
            </p>
            <p className="text-xs text-[var(--muted-foreground)] truncate">
              {user?.role || 'User'}
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}

// =============================================================================
// NAV ITEM COMPONENT
// =============================================================================

interface NavItemComponentProps {
  item: NavItem;
  pathname: string;
  depth?: number;
}

function NavItemComponent({ item, pathname, depth = 0 }: NavItemComponentProps) {
  const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
  const hasChildren = item.children && item.children.length > 0;
  const Icon = item.icon;

  if (hasChildren) {
    return (
      <li>
        <div
          className={cn(
            'flex items-center gap-3 px-3 py-2 rounded-md',
            'text-[var(--muted-foreground)]',
            isActive && 'text-[var(--foreground)]'
          )}
        >
          <Icon className="h-4 w-4" />
          <span className="text-sm font-medium flex-1">{item.label}</span>
          <ChevronRight
            className={cn(
              'h-4 w-4 transition-transform duration-200',
              isActive && 'transform rotate-90'
            )}
          />
        </div>
        {isActive && (
          <ul className="mt-1 ml-4 space-y-1 border-l border-[var(--border)] pl-3">
            {item.children!.map((child) => (
              <NavItemComponent
                key={child.href}
                item={child}
                pathname={pathname}
                depth={depth + 1}
              />
            ))}
          </ul>
        )}
      </li>
    );
  }

  return (
    <li>
      <Link
        href={item.href}
        className={cn(
          'flex items-center gap-3 px-3 py-2 rounded-md',
          'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
          'hover:bg-[var(--muted)] transition-colors duration-150',
          isActive && 'bg-[var(--sv-primary)]/10 text-[var(--sv-primary)] font-medium'
        )}
      >
        <Icon className="h-4 w-4" />
        <span className="text-sm">{item.label}</span>
        {item.badge && (
          <span className="ml-auto text-xs bg-[var(--sv-primary)] text-white px-1.5 py-0.5 rounded-full">
            {item.badge}
          </span>
        )}
      </Link>
    </li>
  );
}
