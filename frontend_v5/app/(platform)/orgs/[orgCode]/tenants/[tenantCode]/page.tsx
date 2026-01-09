// =============================================================================
// SOLVEREIGN Platform Admin - Tenant Detail
// =============================================================================
// Shows tenant details, sites list, entitlements, and status/escalations.
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Building,
  MapPin,
  Package,
  Plus,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  AlertCircle,
  Settings,
  Power,
  PowerOff,
  Shield,
  Clock,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { PlatformStatusBadge, toEntityStatus } from '@/components/ui/platform-status-badge';

interface Tenant {
  id: string;
  tenant_code: string;
  name: string;
  is_active: boolean;
  owner_org_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface Site {
  id: string;
  site_code: string;
  name: string;
  is_active: boolean;
  tenant_id: string;
  timezone: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

interface Entitlement {
  id: string;
  tenant_id: string;
  pack_id: string;
  is_enabled: boolean;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface TenantStatus {
  overall_status: 'healthy' | 'degraded' | 'blocked';
  worst_severity: 'S0' | 'S1' | 'S2' | 'S3' | null;
  blocked_count: number;
  degraded_count: number;
}

interface Escalation {
  id: string;
  scope_type: string;
  scope_id: string | null;
  status: string;
  severity: string;
  reason_code: string;
  reason_message: string;
  fix_steps: string[];
  started_at: string;
}

// Pack definitions (would normally come from backend)
const AVAILABLE_PACKS = [
  {
    id: 'shift-optimizer',
    name: 'Shift Optimizer',
    description: 'Automated driver scheduling with compliance audits',
    icon: Clock,
  },
  {
    id: 'routing',
    name: 'Routing Pack',
    description: 'VRPTW route optimization with OSRM/OR-Tools',
    icon: MapPin,
  },
];

export default function TenantDetailPage() {
  const params = useParams();
  const orgCode = params.orgCode as string;
  const tenantCode = params.tenantCode as string;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [entitlements, setEntitlements] = useState<Entitlement[]>([]);
  const [status, setStatus] = useState<TenantStatus | null>(null);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'sites' | 'entitlements' | 'status'>('sites');
  const [showCreateSiteModal, setShowCreateSiteModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tenantRes, sitesRes, entitlementsRes] = await Promise.all([
        fetch(`/api/platform/tenants/${tenantCode}`),
        fetch(`/api/platform/tenants/${tenantCode}/sites`),
        fetch(`/api/platform/tenants/${tenantCode}/entitlements`),
      ]);

      if (!tenantRes.ok) {
        if (tenantRes.status === 404) {
          throw new Error('Tenant not found');
        }
        throw new Error('Failed to fetch tenant');
      }

      const tenantData = await tenantRes.json();
      setTenant(tenantData);

      if (sitesRes.ok) {
        const sitesData = await sitesRes.json();
        setSites(sitesData || []);
      }

      if (entitlementsRes.ok) {
        const entitlementsData = await entitlementsRes.json();
        setEntitlements(entitlementsData || []);
      }

      // Fetch tenant-specific status
      const statusRes = await fetch(
        `/api/platform/status?scope_type=tenant&scope_id=${tenantData.id}`
      );
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setStatus(statusData);
      }

      // Fetch active escalations
      const escalationsRes = await fetch(
        `/api/platform/escalations?scope_type=tenant&scope_id=${tenantData.id}`
      );
      if (escalationsRes.ok) {
        const escalationsData = await escalationsRes.json();
        setEscalations(escalationsData || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [tenantCode]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleToggleActive = async () => {
    if (!tenant) return;

    try {
      const res = await fetch(`/api/platform/tenants/${tenantCode}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !tenant.is_active }),
      });

      if (!res.ok) {
        throw new Error('Failed to update tenant');
      }

      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleToggleEntitlement = async (packId: string, currentEnabled: boolean) => {
    try {
      const res = await fetch(`/api/platform/tenants/${tenantCode}/entitlements/${packId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_enabled: !currentEnabled }),
      });

      if (!res.ok) {
        throw new Error('Failed to update entitlement');
      }

      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const getStatusColor = (status: string | undefined) => {
    switch (status) {
      case 'blocked':
        return 'text-red-400 bg-red-500/10 border-red-500/20';
      case 'degraded':
        return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20';
      default:
        return 'text-green-400 bg-green-500/10 border-green-500/20';
    }
  };

  const getStatusIcon = (status: string | undefined) => {
    switch (status) {
      case 'blocked':
        return <AlertTriangle className="h-5 w-5" />;
      case 'degraded':
        return <AlertCircle className="h-5 w-5" />;
      default:
        return <CheckCircle className="h-5 w-5" />;
    }
  };

  const isPackEnabled = (packId: string) => {
    return entitlements.some((e) => e.pack_id === packId && e.is_enabled);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-6 w-6 animate-spin text-[var(--sv-gray-400)]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Link
          href={`/platform/orgs/${orgCode}`}
          className="inline-flex items-center gap-2 text-sm text-[var(--sv-gray-400)] hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Organization
        </Link>
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
          <p className="text-red-400">{error}</p>
          <button
            onClick={fetchData}
            className="mt-2 text-sm text-red-400 hover:text-red-300"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!tenant) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Link
        href={`/platform/orgs/${orgCode}`}
        className="inline-flex items-center gap-2 text-sm text-[var(--sv-gray-400)] hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to {orgCode}
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="h-14 w-14 rounded-xl bg-blue-500/10 flex items-center justify-center">
            <Building className="h-7 w-7 text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold text-white">{tenant.name}</h1>
              <PlatformStatusBadge
                status={toEntityStatus(tenant.is_active)}
                entityType="tenant"
              />
            </div>
            <p className="text-sm text-[var(--sv-gray-400)] mt-1">
              {tenant.tenant_code} &middot; Created{' '}
              {new Date(tenant.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowEditModal(true)}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm',
              'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
              'hover:bg-[var(--sv-gray-700)] transition-colors'
            )}
          >
            <Settings className="h-4 w-4" />
            Edit
          </button>
          <button
            onClick={handleToggleActive}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm',
              tenant.is_active
                ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                : 'bg-green-500/10 text-green-400 hover:bg-green-500/20',
              'transition-colors'
            )}
          >
            {tenant.is_active ? (
              <>
                <PowerOff className="h-4 w-4" />
                Deactivate
              </>
            ) : (
              <>
                <Power className="h-4 w-4" />
                Activate
              </>
            )}
          </button>
        </div>
      </div>

      {/* Status Banner */}
      {status && status.overall_status !== 'healthy' && (
        <div
          className={cn(
            'flex items-center gap-3 p-4 rounded-lg border',
            getStatusColor(status.overall_status)
          )}
        >
          {getStatusIcon(status.overall_status)}
          <div className="flex-1">
            <p className="font-medium">
              Tenant {status.overall_status === 'blocked' ? 'Blocked' : 'Degraded'}
            </p>
            <p className="text-sm opacity-80">
              {status.blocked_count} blocked, {status.degraded_count} degraded scopes
            </p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-[var(--sv-gray-700)]">
        <nav className="flex gap-4">
          {[
            { id: 'sites', label: 'Sites', icon: MapPin, count: sites.length },
            { id: 'entitlements', label: 'Entitlements', icon: Package, count: entitlements.filter(e => e.is_enabled).length },
            { id: 'status', label: 'Status & Escalations', icon: Shield, count: escalations.length },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={cn(
                'flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 -mb-[2px] transition-colors',
                activeTab === tab.id
                  ? 'text-[var(--sv-primary)] border-[var(--sv-primary)]'
                  : 'text-[var(--sv-gray-400)] border-transparent hover:text-white'
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
              {tab.count > 0 && (
                <span
                  className={cn(
                    'px-1.5 py-0.5 rounded text-xs',
                    activeTab === tab.id
                      ? 'bg-[var(--sv-primary)]/10 text-[var(--sv-primary)]'
                      : 'bg-[var(--sv-gray-700)] text-[var(--sv-gray-400)]'
                  )}
                >
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === 'sites' && (
        <SitesTab
          sites={sites}
          onCreateSite={() => setShowCreateSiteModal(true)}
        />
      )}

      {activeTab === 'entitlements' && (
        <EntitlementsTab
          entitlements={entitlements}
          onToggle={handleToggleEntitlement}
          isPackEnabled={isPackEnabled}
        />
      )}

      {activeTab === 'status' && (
        <StatusTab
          status={status}
          escalations={escalations}
          tenantId={tenant.id}
          onRefresh={fetchData}
        />
      )}

      {/* Create Site Modal */}
      {showCreateSiteModal && (
        <CreateSiteModal
          tenantCode={tenantCode}
          onClose={() => setShowCreateSiteModal(false)}
          onCreated={() => {
            setShowCreateSiteModal(false);
            fetchData();
          }}
        />
      )}

      {/* Edit Tenant Modal */}
      {showEditModal && tenant && (
        <EditTenantModal
          tenant={tenant}
          onClose={() => setShowEditModal(false)}
          onUpdated={() => {
            setShowEditModal(false);
            fetchData();
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// Sites Tab
// =============================================================================

interface SitesTabProps {
  sites: Site[];
  onCreateSite: () => void;
}

function SitesTab({ sites, onCreateSite }: SitesTabProps) {
  if (sites.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
        <MapPin className="h-10 w-10 text-[var(--sv-gray-500)] mb-3" />
        <h3 className="text-lg font-medium text-white mb-1">No sites configured</h3>
        <p className="text-sm text-[var(--sv-gray-400)] mb-4 text-center max-w-sm">
          Sites represent physical locations or logical environments for this tenant.
        </p>
        <button
          onClick={onCreateSite}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-lg',
            'bg-[var(--sv-primary)] text-white',
            'hover:bg-[var(--sv-primary-dark)] transition-colors'
          )}
        >
          <Plus className="h-4 w-4" />
          Create First Site
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          onClick={onCreateSite}
          className={cn(
            'flex items-center gap-2 px-3 py-2 rounded-lg text-sm',
            'bg-[var(--sv-primary)] text-white',
            'hover:bg-[var(--sv-primary-dark)] transition-colors'
          )}
        >
          <Plus className="h-4 w-4" />
          Add Site
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sites.map((site) => (
          <div
            key={site.id}
            className={cn(
              'p-4 rounded-lg border',
              'bg-[var(--sv-gray-900)] border-[var(--sv-gray-700)]'
            )}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
                  <MapPin className="h-5 w-5 text-purple-400" />
                </div>
                <div>
                  <h3 className="font-medium text-white">{site.name}</h3>
                  <p className="text-xs text-[var(--sv-gray-400)]">{site.site_code}</p>
                </div>
              </div>
              <PlatformStatusBadge
                status={toEntityStatus(site.is_active)}
                entityType="site"
                size="sm"
              />
            </div>
            <div className="text-sm text-[var(--sv-gray-400)]">
              <p>Timezone: {site.timezone}</p>
              <p>Created {new Date(site.created_at).toLocaleDateString()}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// Entitlements Tab
// =============================================================================

interface EntitlementsTabProps {
  entitlements: Entitlement[];
  onToggle: (packId: string, currentEnabled: boolean) => void;
  isPackEnabled: (packId: string) => boolean;
}

function EntitlementsTab({ onToggle, isPackEnabled }: EntitlementsTabProps) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-[var(--sv-gray-400)]">
        Enable or disable packs for this tenant. Changes take effect immediately.
      </p>

      <div className="grid gap-4">
        {AVAILABLE_PACKS.map((pack) => {
          const enabled = isPackEnabled(pack.id);
          const IconComponent = pack.icon;

          return (
            <div
              key={pack.id}
              className={cn(
                'flex items-center justify-between p-4 rounded-lg border',
                'bg-[var(--sv-gray-900)] border-[var(--sv-gray-700)]'
              )}
            >
              <div className="flex items-center gap-4">
                <div
                  className={cn(
                    'h-12 w-12 rounded-lg flex items-center justify-center',
                    enabled ? 'bg-[var(--sv-primary)]/10' : 'bg-[var(--sv-gray-800)]'
                  )}
                >
                  <IconComponent
                    className={cn(
                      'h-6 w-6',
                      enabled ? 'text-[var(--sv-primary)]' : 'text-[var(--sv-gray-500)]'
                    )}
                  />
                </div>
                <div>
                  <h3 className="font-medium text-white">{pack.name}</h3>
                  <p className="text-sm text-[var(--sv-gray-400)]">{pack.description}</p>
                </div>
              </div>
              <button
                onClick={() => onToggle(pack.id, enabled)}
                className={cn(
                  'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                  enabled ? 'bg-[var(--sv-primary)]' : 'bg-[var(--sv-gray-600)]'
                )}
              >
                <span
                  className={cn(
                    'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                    enabled ? 'translate-x-6' : 'translate-x-1'
                  )}
                />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// =============================================================================
// Status Tab
// =============================================================================

interface StatusTabProps {
  status: TenantStatus | null;
  escalations: Escalation[];
  tenantId: string;
  onRefresh: () => void;
}

function StatusTab({ status, escalations, tenantId, onRefresh }: StatusTabProps) {
  const [resolving, setResolving] = useState<string | null>(null);

  const handleResolve = async (escalation: Escalation) => {
    setResolving(escalation.id);
    try {
      const res = await fetch('/api/platform/escalations/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope_type: escalation.scope_type,
          scope_id: escalation.scope_id,
          reason_code: escalation.reason_code,
          resolved_by: 'platform_admin', // Would come from auth context
        }),
      });

      if (!res.ok) {
        throw new Error('Failed to resolve escalation');
      }

      onRefresh();
    } catch (err) {
      console.error('Error resolving escalation:', err);
    } finally {
      setResolving(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Status Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <p className="text-sm text-[var(--sv-gray-400)] mb-1">Overall Status</p>
          <p className="text-xl font-semibold text-white capitalize">
            {status?.overall_status || 'Healthy'}
          </p>
        </div>
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <p className="text-sm text-[var(--sv-gray-400)] mb-1">Worst Severity</p>
          <p className="text-xl font-semibold text-white">{status?.worst_severity || 'None'}</p>
        </div>
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <p className="text-sm text-[var(--sv-gray-400)] mb-1">Blocked Scopes</p>
          <p className="text-xl font-semibold text-red-400">{status?.blocked_count || 0}</p>
        </div>
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <p className="text-sm text-[var(--sv-gray-400)] mb-1">Degraded Scopes</p>
          <p className="text-xl font-semibold text-yellow-400">{status?.degraded_count || 0}</p>
        </div>
      </div>

      {/* Active Escalations */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-4">Active Escalations</h3>

        {escalations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
            <CheckCircle className="h-10 w-10 text-green-400 mb-3" />
            <p className="text-white font-medium">No active escalations</p>
            <p className="text-sm text-[var(--sv-gray-400)]">All systems operating normally</p>
          </div>
        ) : (
          <div className="space-y-4">
            {escalations.map((esc) => (
              <div
                key={esc.id}
                className={cn(
                  'p-4 rounded-lg border',
                  esc.severity === 'S0' || esc.severity === 'S1'
                    ? 'bg-red-500/10 border-red-500/20'
                    : 'bg-yellow-500/10 border-yellow-500/20'
                )}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <AlertTriangle
                      className={cn(
                        'h-5 w-5 mt-0.5',
                        esc.severity === 'S0' || esc.severity === 'S1'
                          ? 'text-red-400'
                          : 'text-yellow-400'
                      )}
                    />
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={cn(
                            'px-2 py-0.5 rounded text-xs font-medium',
                            esc.severity === 'S0'
                              ? 'bg-red-500/20 text-red-400'
                              : esc.severity === 'S1'
                              ? 'bg-red-500/20 text-red-400'
                              : 'bg-yellow-500/20 text-yellow-400'
                          )}
                        >
                          {esc.severity}
                        </span>
                        <span className="text-sm font-mono text-[var(--sv-gray-400)]">
                          {esc.reason_code}
                        </span>
                      </div>
                      <p className="text-white font-medium">{esc.reason_message}</p>
                      <p className="text-sm text-[var(--sv-gray-400)] mt-1">
                        Started {new Date(esc.started_at).toLocaleString()}
                      </p>
                      {esc.fix_steps && esc.fix_steps.length > 0 && (
                        <div className="mt-3">
                          <p className="text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                            Fix Steps:
                          </p>
                          <ol className="text-sm text-[var(--sv-gray-400)] list-decimal list-inside space-y-1">
                            {esc.fix_steps.map((step, idx) => (
                              <li key={idx}>{step}</li>
                            ))}
                          </ol>
                        </div>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => handleResolve(esc)}
                    disabled={resolving === esc.id}
                    className={cn(
                      'px-3 py-1.5 rounded-lg text-sm',
                      'bg-white/10 text-white',
                      'hover:bg-white/20 transition-colors',
                      'disabled:opacity-50'
                    )}
                  >
                    {resolving === esc.id ? 'Resolving...' : 'Mark Resolved'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// Create Site Modal
// =============================================================================

interface CreateSiteModalProps {
  tenantCode: string;
  onClose: () => void;
  onCreated: () => void;
}

function CreateSiteModal({ tenantCode, onClose, onCreated }: CreateSiteModalProps) {
  const [siteCode, setSiteCode] = useState('');
  const [name, setName] = useState('');
  const [timezone, setTimezone] = useState('Europe/Berlin');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`/api/platform/tenants/${tenantCode}/sites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_code: siteCode, name, timezone }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error?.message || 'Failed to create site');
      }

      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] w-full max-w-md p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Create Site</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Site Code
            </label>
            <input
              type="text"
              value={siteCode}
              onChange={(e) =>
                setSiteCode(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))
              }
              placeholder="e.g., hamburg-hq, munich-depot"
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Site Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Hamburg Headquarters"
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Timezone
            </label>
            <select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            >
              <option value="Europe/Berlin">Europe/Berlin</option>
              <option value="Europe/London">Europe/London</option>
              <option value="Europe/Paris">Europe/Paris</option>
              <option value="America/New_York">America/New_York</option>
              <option value="America/Los_Angeles">America/Los_Angeles</option>
              <option value="Asia/Tokyo">Asia/Tokyo</option>
              <option value="UTC">UTC</option>
            </select>
          </div>

          {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className={cn(
                'flex-1 px-4 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                'hover:bg-[var(--sv-gray-700)] transition-colors'
              )}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !siteCode || !name}
              className={cn(
                'flex-1 px-4 py-2 rounded-lg',
                'bg-[var(--sv-primary)] text-white',
                'hover:bg-[var(--sv-primary-dark)] transition-colors',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              {submitting ? 'Creating...' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// =============================================================================
// Edit Tenant Modal
// =============================================================================

interface EditTenantModalProps {
  tenant: Tenant;
  onClose: () => void;
  onUpdated: () => void;
}

function EditTenantModal({ tenant, onClose, onUpdated }: EditTenantModalProps) {
  const [name, setName] = useState(tenant.name);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`/api/platform/tenants/${tenant.tenant_code}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error?.message || 'Failed to update tenant');
      }

      onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] w-full max-w-md p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Edit Tenant</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Tenant Code
            </label>
            <input
              type="text"
              value={tenant.tenant_code}
              disabled
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-[var(--sv-gray-500)]',
                'cursor-not-allowed'
              )}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Tenant Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
              required
            />
          </div>

          {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className={cn(
                'flex-1 px-4 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                'hover:bg-[var(--sv-gray-700)] transition-colors'
              )}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !name || name === tenant.name}
              className={cn(
                'flex-1 px-4 py-2 rounded-lg',
                'bg-[var(--sv-primary)] text-white',
                'hover:bg-[var(--sv-primary-dark)] transition-colors',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              {submitting ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
