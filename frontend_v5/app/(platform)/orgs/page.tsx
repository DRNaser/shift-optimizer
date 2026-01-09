// =============================================================================
// SOLVEREIGN Platform Admin - Organizations List
// =============================================================================
// Lists all organizations with aggregated health status.
// Shows onboarding wizard when no organizations exist.
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Plus, Building2, RefreshCw, AlertTriangle, CheckCircle, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { OnboardingWizard } from '@/components/platform/onboarding-wizard';
import { PlatformStatusBadge, toEntityStatus } from '@/components/ui/platform-status-badge';

interface Organization {
  id: string;
  org_code: string;
  name: string;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  tenants_count?: number;
}

interface PlatformStatus {
  overall_status: 'healthy' | 'degraded' | 'blocked';
  worst_severity: 'S0' | 'S1' | 'S2' | 'S3' | null;
  blocked_count: number;
  degraded_count: number;
}

export default function OrganizationsPage() {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [isFirstLoad, setIsFirstLoad] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [orgsRes, statusRes] = await Promise.all([
        fetch('/api/platform/orgs'),
        fetch('/api/platform/status'),
      ]);

      if (!orgsRes.ok) throw new Error('Failed to fetch organizations');

      const orgsData = await orgsRes.json();
      setOrgs(orgsData || []);

      // Show wizard on first load if no organizations exist
      if (isFirstLoad && (!orgsData || orgsData.length === 0)) {
        setShowWizard(true);
      }
      setIsFirstLoad(false);

      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setStatus(statusData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [isFirstLoad]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const getStatusColor = (status: string | undefined) => {
    switch (status) {
      case 'blocked':
        return 'text-red-400 bg-red-500/10';
      case 'degraded':
        return 'text-yellow-400 bg-yellow-500/10';
      default:
        return 'text-green-400 bg-green-500/10';
    }
  };

  const getStatusIcon = (status: string | undefined) => {
    switch (status) {
      case 'blocked':
        return <AlertTriangle className="h-4 w-4" />;
      case 'degraded':
        return <AlertCircle className="h-4 w-4" />;
      default:
        return <CheckCircle className="h-4 w-4" />;
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
      <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
        <p className="text-red-400">{error}</p>
        <button
          onClick={fetchData}
          className="mt-2 text-sm text-red-400 hover:text-red-300"
        >
          Retry
        </button>
      </div>
    );
  }

  // Show onboarding wizard when no organizations exist
  if (showWizard) {
    return (
      <OnboardingWizard
        onComplete={() => {
          setShowWizard(false);
          fetchData();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Organizations</h1>
          <p className="text-sm text-[var(--sv-gray-400)] mt-1">
            Manage customer organizations and their tenants
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-lg',
            'bg-[var(--sv-primary)] text-white',
            'hover:bg-[var(--sv-primary-dark)] transition-colors'
          )}
        >
          <Plus className="h-4 w-4" />
          Create Organization
        </button>
      </div>

      {/* Platform Status Banner */}
      {status && status.overall_status !== 'healthy' && (
        <div
          className={cn(
            'flex items-center gap-3 p-4 rounded-lg border',
            status.overall_status === 'blocked'
              ? 'bg-red-500/10 border-red-500/20'
              : 'bg-yellow-500/10 border-yellow-500/20'
          )}
        >
          {getStatusIcon(status.overall_status)}
          <div className="flex-1">
            <p
              className={cn(
                'font-medium',
                status.overall_status === 'blocked' ? 'text-red-400' : 'text-yellow-400'
              )}
            >
              Platform {status.overall_status === 'blocked' ? 'Blocked' : 'Degraded'}
            </p>
            <p className="text-sm text-[var(--sv-gray-400)]">
              {status.blocked_count} blocked, {status.degraded_count} degraded scopes
            </p>
          </div>
          <Link
            href="/platform/escalations"
            className="text-sm text-[var(--sv-primary)] hover:underline"
          >
            View Escalations
          </Link>
        </div>
      )}

      {/* Empty State */}
      {orgs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
          <Building2 className="h-12 w-12 text-[var(--sv-gray-500)] mb-4" />
          <h2 className="text-lg font-medium text-white mb-2">No organizations yet</h2>
          <p className="text-sm text-[var(--sv-gray-400)] mb-4 text-center max-w-md">
            Get started by creating your first customer organization with the onboarding wizard.
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => setShowWizard(true)}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg',
                'bg-[var(--sv-primary)] text-white',
                'hover:bg-[var(--sv-primary-dark)] transition-colors'
              )}
            >
              Start Onboarding Wizard
            </button>
            <button
              onClick={() => setShowCreateModal(true)}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                'hover:bg-[var(--sv-gray-700)] transition-colors'
              )}
            >
              <Plus className="h-4 w-4" />
              Quick Create
            </button>
          </div>
        </div>
      ) : (
        /* Organizations Grid */
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {orgs.map((org) => (
            <Link
              key={org.id}
              href={`/platform/orgs/${org.org_code}`}
              className={cn(
                'block p-4 rounded-lg border transition-colors',
                'bg-[var(--sv-gray-900)] border-[var(--sv-gray-700)]',
                'hover:border-[var(--sv-primary)] hover:bg-[var(--sv-gray-800)]'
              )}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-[var(--sv-primary)]/10 flex items-center justify-center">
                    <Building2 className="h-5 w-5 text-[var(--sv-primary)]" />
                  </div>
                  <div>
                    <h3 className="font-medium text-white">{org.name}</h3>
                    <p className="text-xs text-[var(--sv-gray-400)]">{org.org_code}</p>
                  </div>
                </div>
                <PlatformStatusBadge
                  status={toEntityStatus(org.is_active)}
                  entityType="org"
                  size="sm"
                />
              </div>
              <div className="flex items-center gap-4 text-sm text-[var(--sv-gray-400)]">
                <span>{org.tenants_count || 0} tenants</span>
                <span>Created {new Date(org.created_at).toLocaleDateString()}</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreateOrganizationModal
          onClose={() => setShowCreateModal(false)}
          onCreated={() => {
            setShowCreateModal(false);
            fetchData();
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// Create Organization Modal
// =============================================================================

interface CreateOrganizationModalProps {
  onClose: () => void;
  onCreated: () => void;
}

function CreateOrganizationModal({ onClose, onCreated }: CreateOrganizationModalProps) {
  const [orgCode, setOrgCode] = useState('');
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch('/api/platform/orgs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ org_code: orgCode, name }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error?.message || 'Failed to create organization');
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
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] w-full max-w-md p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Create Organization</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Organization Code
            </label>
            <input
              type="text"
              value={orgCode}
              onChange={(e) => setOrgCode(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
              placeholder="e.g., lts, mediamarkt"
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
              Organization Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., LTS Transport & Logistik GmbH"
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
              disabled={submitting || !orgCode || !name}
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
