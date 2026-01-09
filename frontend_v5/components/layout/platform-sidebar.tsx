// =============================================================================
// SOLVEREIGN Platform Admin Sidebar
// =============================================================================
// Navigation sidebar for platform-level admin console.
// Respects feature flags for conditional nav item visibility.
// =============================================================================

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Building2,
  AlertTriangle,
  Play,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { canAccessFeature, type FeatureFlag } from '@/lib/feature-flags';
import { usePlatformUser } from '@/app/(platform)/layout-client';

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  featureFlag?: FeatureFlag; // Optional - if set, item only shows when flag enabled + role allowed
}

// Only include nav items with existing pages
// Removed: Dashboard, Packs, Health, Audit Log, API Keys, Metriken (no pages exist)
const platformNavItems: NavItem[] = [
  { label: 'Organizations', href: '/orgs', icon: Building2 },
  { label: 'Runs', href: '/runs', icon: Play, featureFlag: 'dispatcherCockpit' },
  { label: 'Escalations', href: '/escalations', icon: AlertTriangle },
];

interface PlatformSidebarProps {
  className?: string;
}

export function PlatformSidebar({ className }: PlatformSidebarProps) {
  const pathname = usePathname();
  const user = usePlatformUser();

  // Filter nav items by feature flags
  const visibleNavItems = platformNavItems.filter((item) => {
    if (!item.featureFlag) return true; // No flag = always visible
    return canAccessFeature(item.featureFlag, user.role);
  });

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
        <div className="h-8 w-8 rounded-lg bg-[var(--sv-primary)] flex items-center justify-center">
          <span className="text-white font-bold text-sm">SV</span>
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold">SOLVEREIGN</span>
          <span className="text-xs text-[var(--sv-gray-400)]">
            Platform Admin
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-2">
        <ul className="space-y-1">
          {visibleNavItems.map((item) => {
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
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* User Section */}
      <div className="border-t border-[var(--sv-gray-700)] p-4">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-[var(--sv-primary)] flex items-center justify-center">
            <span className="text-white text-xs font-medium">
              {user.name.slice(0, 2).toUpperCase()}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">
              {user.name}
            </p>
            <p className="text-xs text-[var(--sv-gray-400)] truncate">
              {user.email || user.role}
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}
