// =============================================================================
// SOLVEREIGN Platform Home - Pack Navigation Dashboard
// =============================================================================
// Central hub for navigating between platform features and packs.
// Shows current tenant/site context and available modules.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
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
  Camera,
  Clock,
  AlertTriangle,
  ScrollText,
  FileJson,
  Loader2,
  Snowflake,
} from 'lucide-react';
import { usePlatformUser } from '../layout-client';

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
// DASHBOARD DATA TYPES
// =============================================================================

interface DashboardData {
  last_snapshot: {
    id: number;
    version_number: number;
    published_at: string;
    is_frozen: boolean;
  } | null;
  last_plan: {
    id: number;
    plan_state: string;
    created_at: string;
    audit_passed_count: number;
    audit_failed_count: number;
  } | null;
  open_items: {
    pending_acks: number;
    failed_notifications: number;
    draft_plans: number;
  };
}

// =============================================================================
// COMPONENTS
// =============================================================================

function DashboardWidgets() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const user = usePlatformUser();

  useEffect(() => {
    async function fetchDashboard() {
      // Only fetch if user has tenant context
      if (!user.tenant_id && user.role !== 'platform_admin') {
        setLoading(false);
        return;
      }

      try {
        const res = await fetch('/api/tenant/dashboard');
        const result = await res.json();
        if (res.ok && result.success) {
          setData(result);
        }
      } catch {
        // Ignore errors - dashboard is optional
      } finally {
        setLoading(false);
      }
    }
    if (!user.isLoading) {
      fetchDashboard();
    }
  }, [user.tenant_id, user.role, user.isLoading]);

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 animate-pulse">
            <div className="h-4 bg-slate-700 rounded w-24 mb-3"></div>
            <div className="h-8 bg-slate-700 rounded w-16"></div>
          </div>
        ))}
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const formatDate = (dateStr: string) => new Date(dateStr).toLocaleDateString();

  return (
    <div className="space-y-4 mb-6">
      {/* Main Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Last Snapshot */}
        <Link
          href="/packs/roster/snapshots"
          className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 hover:border-slate-600 transition-colors"
        >
          <div className="flex items-center gap-2 text-slate-400 text-sm mb-2">
            <Camera className="w-4 h-4" />
            Last Snapshot
          </div>
          {data.last_snapshot ? (
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-semibold text-white">
                  v{data.last_snapshot.version_number}
                </span>
                {data.last_snapshot.is_frozen && (
                  <span className="flex items-center gap-1 text-cyan-400 text-xs">
                    <Snowflake className="w-3 h-3" />
                    FROZEN
                  </span>
                )}
              </div>
              <span className="text-xs text-slate-500 flex items-center gap-1 mt-1">
                <Clock className="w-3 h-3" />
                {formatDate(data.last_snapshot.published_at)}
              </span>
            </div>
          ) : (
            <span className="text-slate-500">No snapshots</span>
          )}
        </Link>

        {/* Last Plan */}
        <Link
          href="/packs/roster/plans"
          className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 hover:border-slate-600 transition-colors"
        >
          <div className="flex items-center gap-2 text-slate-400 text-sm mb-2">
            <FileText className="w-4 h-4" />
            Last Plan
          </div>
          {data.last_plan ? (
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-semibold text-white">
                  #{data.last_plan.id}
                </span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                  data.last_plan.plan_state === 'PUBLISHED' ? 'bg-emerald-500/20 text-emerald-400' :
                  data.last_plan.plan_state === 'APPROVED' ? 'bg-blue-500/20 text-blue-400' :
                  data.last_plan.plan_state === 'SOLVED' ? 'bg-purple-500/20 text-purple-400' :
                  'bg-slate-500/20 text-slate-400'
                }`}>
                  {data.last_plan.plan_state}
                </span>
              </div>
              <span className="text-xs text-slate-500 flex items-center gap-1 mt-1">
                <Clock className="w-3 h-3" />
                {formatDate(data.last_plan.created_at)}
              </span>
            </div>
          ) : (
            <span className="text-slate-500">No plans</span>
          )}
        </Link>

        {/* Open Items */}
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
          <div className="flex items-center gap-2 text-slate-400 text-sm mb-2">
            <AlertTriangle className="w-4 h-4" />
            Open Items
          </div>
          <div className="flex items-center gap-4">
            {data.open_items.pending_acks > 0 && (
              <div className="text-center">
                <span className="text-xl font-semibold text-amber-400">{data.open_items.pending_acks}</span>
                <p className="text-xs text-slate-500">Pending ACKs</p>
              </div>
            )}
            {data.open_items.failed_notifications > 0 && (
              <div className="text-center">
                <span className="text-xl font-semibold text-red-400">{data.open_items.failed_notifications}</span>
                <p className="text-xs text-slate-500">Failed Notifs</p>
              </div>
            )}
            {data.open_items.draft_plans > 0 && (
              <div className="text-center">
                <span className="text-xl font-semibold text-slate-300">{data.open_items.draft_plans}</span>
                <p className="text-xs text-slate-500">Draft Plans</p>
              </div>
            )}
            {data.open_items.pending_acks === 0 && data.open_items.failed_notifications === 0 && data.open_items.draft_plans === 0 && (
              <span className="text-emerald-400 text-sm">All clear</span>
            )}
          </div>
        </div>
      </div>

      {/* Quick Links */}
      <div className="flex items-center gap-3">
        <Link
          href="/platform-admin/evidence"
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-slate-400 hover:text-white hover:border-slate-600 transition-colors"
        >
          <FileJson className="w-4 h-4" />
          Evidence Viewer
        </Link>
        <Link
          href="/platform-admin/audit"
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-slate-400 hover:text-white hover:border-slate-600 transition-colors"
        >
          <ScrollText className="w-4 h-4" />
          Audit Log
        </Link>
      </div>
    </div>
  );
}

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
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
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
        <div className="h-8 w-px bg-slate-700"></div>

        {/* Context Tags */}
        <div className="flex items-center gap-2">
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
// PAGE COMPONENT
// =============================================================================

export default function PlatformHomePage() {
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

      {/* Dashboard Widgets */}
      <DashboardWidgets />

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
