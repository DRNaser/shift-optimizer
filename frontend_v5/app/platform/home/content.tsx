// =============================================================================
// SOLVEREIGN Platform Home - Pack Navigation Dashboard (Client Content)
// =============================================================================
// Central hub for navigating between platform features and packs.
// Shows current tenant/site context and available modules.
// =============================================================================

'use client';

import Link from 'next/link';
import {
  LayoutGrid,
  Users,
  Truck,
  FileText,
  Shield,
  Settings,
  Building2,
  Calendar,
  ClipboardList,
} from 'lucide-react';
import { usePlatformUser } from '../../(platform)/layout-client';

// =============================================================================
// PACK DEFINITIONS
// =============================================================================

interface PackTile {
  id: string;
  name: string;
  description: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  badge?: string;
  requiredRoles?: string[];
}

const PLATFORM_TILES: PackTile[] = [
  {
    id: 'portal-admin',
    name: 'Portal Admin',
    description: 'Driver portal management, notifications, acknowledgments',
    href: '/portal-admin/dashboard',
    icon: Users,
    color: 'from-blue-500 to-blue-600',
  },
  {
    id: 'orgs',
    name: 'Organizations',
    description: 'Manage tenants, sites, and hierarchy',
    href: '/orgs',
    icon: Building2,
    color: 'from-purple-500 to-purple-600',
    requiredRoles: ['platform_admin'],
  },
  {
    id: 'runs',
    name: 'Solver Runs',
    description: 'View optimization history and results',
    href: '/runs',
    icon: ClipboardList,
    color: 'from-emerald-500 to-emerald-600',
  },
  {
    id: 'escalations',
    name: 'Escalations',
    description: 'Review and resolve system alerts',
    href: '/escalations',
    icon: Shield,
    color: 'from-red-500 to-red-600',
    requiredRoles: ['platform_admin', 'operator_admin'],
  },
];

const PACK_TILES: PackTile[] = [
  {
    id: 'roster',
    name: 'Roster Pack',
    description: 'Shift optimization workbench with CSV import/export',
    href: '/packs/roster/workbench',
    icon: Calendar,
    color: 'from-amber-500 to-orange-600',
    badge: 'Core',
  },
  {
    id: 'routing',
    name: 'Routing Pack',
    description: 'VRPTW solver for vehicle routing optimization',
    href: '/packs/routing',
    icon: Truck,
    color: 'from-cyan-500 to-cyan-600',
    badge: 'Pro',
  },
  {
    id: 'masterdata',
    name: 'Master Data',
    description: 'Manage drivers, vehicles, and locations',
    href: '/packs/masterdata',
    icon: FileText,
    color: 'from-slate-500 to-slate-600',
  },
];

// =============================================================================
// COMPONENTS
// =============================================================================

function PackCard({ pack }: { pack: PackTile }) {
  const Icon = pack.icon;

  return (
    <Link
      href={pack.href}
      className="group relative block p-6 bg-slate-800/50 border border-slate-700/50 rounded-xl hover:border-slate-600 hover:bg-slate-800/80 transition-all duration-200"
    >
      {/* Badge */}
      {pack.badge && (
        <span className="absolute top-4 right-4 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider bg-slate-700 text-slate-300 rounded">
          {pack.badge}
        </span>
      )}

      {/* Icon */}
      <div className={`w-12 h-12 rounded-lg bg-gradient-to-br ${pack.color} flex items-center justify-center mb-4 group-hover:scale-105 transition-transform`}>
        <Icon className="w-6 h-6 text-white" />
      </div>

      {/* Content */}
      <h3 className="text-lg font-semibold text-white mb-1 group-hover:text-slate-100">
        {pack.name}
      </h3>
      <p className="text-sm text-slate-400 line-clamp-2">
        {pack.description}
      </p>
    </Link>
  );
}

function ContextBanner() {
  const user = usePlatformUser();

  if (user.isLoading) {
    return (
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 animate-pulse">
        <div className="h-4 bg-slate-700 rounded w-48"></div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 flex items-center justify-between flex-wrap gap-4">
      <div className="flex items-center gap-4 flex-wrap">
        {/* User Info */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center">
            <span className="text-white font-semibold text-sm">
              {user.email?.charAt(0)?.toUpperCase() || '?'}
            </span>
          </div>
          <div>
            <p className="text-sm font-medium text-white">{user.name}</p>
            <p className="text-xs text-slate-400">{user.email}</p>
          </div>
        </div>

        {/* Divider */}
        <div className="h-8 w-px bg-slate-700 hidden sm:block"></div>

        {/* Context Tags */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="px-2 py-1 bg-emerald-500/10 text-emerald-400 text-xs font-medium rounded border border-emerald-500/20">
            {user.role || 'Unknown Role'}
          </span>
          {user.tenant_id && (
            <span className="px-2 py-1 bg-blue-500/10 text-blue-400 text-xs font-medium rounded border border-blue-500/20">
              Tenant {user.tenant_id}
            </span>
          )}
          {user.site_id && (
            <span className="px-2 py-1 bg-purple-500/10 text-purple-400 text-xs font-medium rounded border border-purple-500/20">
              Site {user.site_id}
            </span>
          )}
        </div>
      </div>

      {/* Permissions Count */}
      {user.permissions && user.permissions.length > 0 && (
        <span className="text-xs text-slate-500">
          {user.permissions.length} permissions
        </span>
      )}
    </div>
  );
}

// =============================================================================
// CONTENT COMPONENT
// =============================================================================

export default function PlatformHomeContent() {
  const user = usePlatformUser();

  // Filter tiles based on user role
  const filteredPlatformTiles = PLATFORM_TILES.filter(tile => {
    if (!tile.requiredRoles) return true;
    return tile.requiredRoles.includes(user.role);
  });

  return (
    <div className="space-y-8">
      {/* Context Banner */}
      <ContextBanner />

      {/* Platform Features */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <LayoutGrid className="w-5 h-5 text-slate-500" />
          <h2 className="text-lg font-semibold text-white">Platform</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {filteredPlatformTiles.map(tile => (
            <PackCard key={tile.id} pack={tile} />
          ))}
        </div>
      </section>

      {/* Packs */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Settings className="w-5 h-5 text-slate-500" />
          <h2 className="text-lg font-semibold text-white">Packs</h2>
          <span className="text-xs text-slate-500 ml-2">Enabled modules</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {PACK_TILES.map(tile => (
            <PackCard key={tile.id} pack={tile} />
          ))}
        </div>
      </section>

      {/* Quick Stats */}
      <section className="pt-4 border-t border-slate-700/50">
        <p className="text-xs text-slate-500 text-center">
          SOLVEREIGN Platform v4.4.0 | Internal RBAC Active | Wien Pilot Ready
        </p>
      </section>
    </div>
  );
}
