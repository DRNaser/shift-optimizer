// =============================================================================
// SOLVEREIGN Platform Admin - Organization Detail
// =============================================================================
// Shows organization details, tenants list, and status timeline.
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Building2,
  Users,
  Plus,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  AlertCircle,
  Settings,
  Power,
  PowerOff,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { PlatformStatusBadge, toEntityStatus } from '@/components/ui/platform-status-badge';

interface Organization {
  id: string;
  org_code: string;
  name: string;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface Tenant {
  id: string;
  tenant_code: string;
  name: string;
  is_active: boolean;
  owner_org_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
  sites_count?: number;
}

interface OrgStatus {
  overall_status: 'healthy' | 'degraded' | 'blocked';
  worst_severity: 'S0' | 'S1' | 'S2' | 'S3' | null;
  blocked_count: number;
  degraded_count: number;
}

export default function OrganizationDetailPage() {
  const params = useParams();
  const orgCode = params.orgCode as string;

  const [org, setOrg] = useState<Organization | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [status, setStatus] = useState<OrgStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [orgRes, tenantsRes] = await Promise.all([
        fetch(`/api/platform/orgs/${orgCode}`),
        fetch(`/api/platform/orgs/${orgCode}/tenants`),
      ]);

      if (!orgRes.ok) {
        if (orgRes.status === 404) {
          throw new Error('Organization not found');
        }
        throw new Error('Failed to fetch organization');
      }

      const orgData = await orgRes.json();
      setOrg(orgData);

      if (tenantsRes.ok) {
        const tenantsData = await tenantsRes.json();
        setTenants(tenantsData || []);
      }

      // Fetch org-specific status
      const statusRes = await fetch(`/api/platform/status?scope_type=org&scope_id=${orgData.id}`);
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setStatus(statusData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [orgCode]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleToggleActive = async () => {
    if (!org) return;

    try {
      const res = await fetch(`/api/platform/orgs/${orgCode}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !org.is_active }),
      });

      if (!res.ok) {
        throw new Error('Failed to update organization');
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
          href="/platform/orgs"
          className="inline-flex items-center gap-2 text-sm text-[var(--sv-gray-400)] hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Organizations
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

  if (!org) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Link
        href="/platform/orgs"
        className="inline-flex items-center gap-2 text-sm text-[var(--sv-gray-400)] hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Organizations
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="h-14 w-14 rounded-xl bg-[var(--sv-primary)]/10 flex items-center justify-center">
            <Building2 className="h-7 w-7 text-[var(--sv-primary)]" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold text-white">{org.name}</h1>
              <PlatformStatusBadge
                status={toEntityStatus(org.is_active)}
                entityType="org"
              />
            </div>
            <p className="text-sm text-[var(--sv-gray-400)] mt-1">
              {org.org_code} &middot; Created {new Date(org.created_at).toLocaleDateString()}
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
              org.is_active
                ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                : 'bg-green-500/10 text-green-400 hover:bg-green-500/20',
              'transition-colors'
            )}
          >
            {org.is_active ? (
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
              Organization {status.overall_status === 'blocked' ? 'Blocked' : 'Degraded'}
            </p>
            <p className="text-sm opacity-80">
              {status.blocked_count} blocked, {status.degraded_count} degraded scopes
            </p>
          </div>
          <Link
            href={`/platform/escalations?org=${orgCode}`}
            className="text-sm hover:underline"
          >
            View Escalations
          </Link>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
              <Users className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-white">{tenants.length}</p>
              <p className="text-sm text-[var(--sv-gray-400)]">Tenants</p>
            </div>
          </div>
        </div>
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-green-500/10 flex items-center justify-center">
              <CheckCircle className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-white">
                {tenants.filter((t) => t.is_active).length}
              </p>
              <p className="text-sm text-[var(--sv-gray-400)]">Active Tenants</p>
            </div>
          </div>
        </div>
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                'h-10 w-10 rounded-lg flex items-center justify-center',
                status?.overall_status === 'blocked'
                  ? 'bg-red-500/10'
                  : status?.overall_status === 'degraded'
                  ? 'bg-yellow-500/10'
                  : 'bg-green-500/10'
              )}
            >
              {getStatusIcon(status?.overall_status)}
            </div>
            <div>
              <p className="text-2xl font-semibold text-white capitalize">
                {status?.overall_status || 'Healthy'}
              </p>
              <p className="text-sm text-[var(--sv-gray-400)]">Health Status</p>
            </div>
          </div>
        </div>
      </div>

      {/* Tenants Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Tenants</h2>
          <button
            onClick={() => setShowCreateModal(true)}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm',
              'bg-[var(--sv-primary)] text-white',
              'hover:bg-[var(--sv-primary-dark)] transition-colors'
            )}
          >
            <Plus className="h-4 w-4" />
            Create Tenant
          </button>
        </div>

        {tenants.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
            <Users className="h-10 w-10 text-[var(--sv-gray-500)] mb-3" />
            <h3 className="text-lg font-medium text-white mb-1">No tenants yet</h3>
            <p className="text-sm text-[var(--sv-gray-400)] mb-4 text-center max-w-sm">
              Create your first tenant to start configuring sites and entitlements.
            </p>
            <button
              onClick={() => setShowCreateModal(true)}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg',
                'bg-[var(--sv-primary)] text-white',
                'hover:bg-[var(--sv-primary-dark)] transition-colors'
              )}
            >
              <Plus className="h-4 w-4" />
              Create First Tenant
            </button>
          </div>
        ) : (
          <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--sv-gray-700)]">
                  <th className="text-left text-xs font-medium text-[var(--sv-gray-400)] uppercase tracking-wider px-4 py-3">
                    Tenant
                  </th>
                  <th className="text-left text-xs font-medium text-[var(--sv-gray-400)] uppercase tracking-wider px-4 py-3">
                    Status
                  </th>
                  <th className="text-left text-xs font-medium text-[var(--sv-gray-400)] uppercase tracking-wider px-4 py-3">
                    Sites
                  </th>
                  <th className="text-left text-xs font-medium text-[var(--sv-gray-400)] uppercase tracking-wider px-4 py-3">
                    Created
                  </th>
                  <th className="text-right text-xs font-medium text-[var(--sv-gray-400)] uppercase tracking-wider px-4 py-3">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--sv-gray-800)]">
                {tenants.map((tenant) => (
                  <tr
                    key={tenant.id}
                    className="hover:bg-[var(--sv-gray-800)] transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div>
                        <p className="font-medium text-white">{tenant.name}</p>
                        <p className="text-xs text-[var(--sv-gray-400)]">
                          {tenant.tenant_code}
                        </p>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <PlatformStatusBadge
                        status={toEntityStatus(tenant.is_active)}
                        entityType="tenant"
                        size="sm"
                      />
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--sv-gray-300)]">
                      {tenant.sites_count || 0} sites
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--sv-gray-400)]">
                      {new Date(tenant.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/platform/orgs/${orgCode}/tenants/${tenant.tenant_code}`}
                        className="text-sm text-[var(--sv-primary)] hover:underline"
                      >
                        Manage
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Tenant Modal */}
      {showCreateModal && (
        <CreateTenantModal
          orgCode={orgCode}
          onClose={() => setShowCreateModal(false)}
          onCreated={() => {
            setShowCreateModal(false);
            fetchData();
          }}
        />
      )}

      {/* Edit Organization Modal */}
      {showEditModal && org && (
        <EditOrganizationModal
          org={org}
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
// Create Tenant Modal
// =============================================================================

interface CreateTenantModalProps {
  orgCode: string;
  onClose: () => void;
  onCreated: () => void;
}

function CreateTenantModal({ orgCode, onClose, onCreated }: CreateTenantModalProps) {
  const [tenantCode, setTenantCode] = useState('');
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`/api/platform/orgs/${orgCode}/tenants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_code: tenantCode, name }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error?.message || 'Failed to create tenant');
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
        <h2 className="text-lg font-semibold text-white mb-4">Create Tenant</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Tenant Code
            </label>
            <input
              type="text"
              value={tenantCode}
              onChange={(e) =>
                setTenantCode(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))
              }
              placeholder="e.g., production, staging"
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
              required
            />
            <p className="text-xs text-[var(--sv-gray-500)] mt-1">
              URL-safe identifier (lowercase, no spaces)
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Tenant Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Production Environment"
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
              disabled={submitting || !tenantCode || !name}
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
// Edit Organization Modal
// =============================================================================

interface EditOrganizationModalProps {
  org: Organization;
  onClose: () => void;
  onUpdated: () => void;
}

function EditOrganizationModal({ org, onClose, onUpdated }: EditOrganizationModalProps) {
  const [name, setName] = useState(org.name);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`/api/platform/orgs/${org.org_code}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error?.message || 'Failed to update organization');
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
        <h2 className="text-lg font-semibold text-white mb-4">Edit Organization</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Organization Code
            </label>
            <input
              type="text"
              value={org.org_code}
              disabled
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-[var(--sv-gray-500)]',
                'cursor-not-allowed'
              )}
            />
            <p className="text-xs text-[var(--sv-gray-500)] mt-1">
              Organization code cannot be changed
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Organization Name
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
              disabled={submitting || !name || name === org.name}
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
