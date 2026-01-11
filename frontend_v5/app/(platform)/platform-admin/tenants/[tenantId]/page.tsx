// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Tenant Detail
// =============================================================================
// View and manage a single tenant.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Building2, ArrowLeft, MapPin, Users, Plus, Settings, Clock,
  Check, AlertCircle, Play, CheckCircle
} from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

interface Tenant {
  id: number;
  name: string;
  is_active: boolean;
  created_at: string;
  user_count?: number;
  site_count?: number;
}

interface Site {
  id: number;
  tenant_id: number;
  name: string;
  code: string | null;
  created_at: string;
}

interface ApiError {
  error_code?: string;
  message?: string;
  detail?: string;
}

export default function TenantDetailPage() {
  const params = useParams();
  const router = useRouter();
  const tenantId = params.tenantId as string;

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  // New site form
  const [showNewSiteForm, setShowNewSiteForm] = useState(false);
  const [newSiteName, setNewSiteName] = useState('');
  const [newSiteCode, setNewSiteCode] = useState('');
  const [creatingSite, setCreatingSite] = useState(false);
  const [siteError, setSiteError] = useState<string | null>(null);

  // Context setting
  const [settingContext, setSettingContext] = useState(false);
  const [contextSuccess, setContextSuccess] = useState(false);

  useEffect(() => {
    async function loadData() {
      try {
        const [tenantRes, sitesRes] = await Promise.all([
          fetch(`/api/platform-admin/tenants/${tenantId}`),
          fetch(`/api/platform-admin/tenants/${tenantId}/sites`),
        ]);

        if (!tenantRes.ok) {
          const data = await tenantRes.json();
          setError({
            error_code: data.error_code || `HTTP_${tenantRes.status}`,
            message: data.message || data.detail || 'Failed to load tenant',
          });
          return;
        }

        setTenant(await tenantRes.json());

        if (sitesRes.ok) {
          setSites(await sitesRes.json());
        }
      } catch (err) {
        setError({
          error_code: 'NETWORK_ERROR',
          message: err instanceof Error ? err.message : 'Failed to load tenant',
        });
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [tenantId]);

  const handleCreateSite = async (e: React.FormEvent) => {
    e.preventDefault();
    setSiteError(null);
    setCreatingSite(true);

    try {
      const res = await fetch(`/api/platform-admin/tenants/${tenantId}/sites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newSiteName,
          code: newSiteCode || undefined,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || data.message || 'Failed to create site');
      }

      const newSite = await res.json();
      setSites([...sites, newSite]);
      setNewSiteName('');
      setNewSiteCode('');
      setShowNewSiteForm(false);
    } catch (err) {
      setSiteError(err instanceof Error ? err.message : 'Failed to create site');
    } finally {
      setCreatingSite(false);
    }
  };

  const handleSetActiveContext = async (siteId?: number) => {
    setSettingContext(true);
    setContextSuccess(false);

    try {
      const res = await fetch('/api/platform-admin/context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: parseInt(tenantId),
          site_id: siteId,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail?.message || data.message || 'Failed to set context');
      }

      setContextSuccess(true);
      // Reload page to update UI with new context
      setTimeout(() => {
        window.location.reload();
      }, 1500);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to set context');
    } finally {
      setSettingContext(false);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--sv-gray-900)] flex items-center justify-center">
        <div className="h-8 w-8 border-4 border-[var(--sv-primary)]/30 border-t-[var(--sv-primary)] rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
        <div className="max-w-4xl mx-auto">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-2 text-[var(--sv-gray-400)] hover:text-white mb-6"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
            <div className="text-red-400 font-medium">Failed to load tenant</div>
            <div className="text-red-400/80 text-sm mt-1">
              <span className="font-mono">{error.error_code}</span>: {error.message}
            </div>
            <div className="text-[var(--sv-gray-500)] text-xs mt-2 font-mono">
              GET /api/platform-admin/tenants/{tenantId}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!tenant) {
    return null;
  }

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-4xl mx-auto">
        {/* Back Button */}
        <button
          onClick={() => router.push('/platform-admin/tenants')}
          className="flex items-center gap-2 text-[var(--sv-gray-400)] hover:text-white mb-6"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Tenants
        </button>

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-lg bg-blue-500/10">
              <Building2 className="h-8 w-8 text-blue-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">{tenant.name}</h1>
              <div className="flex items-center gap-4 mt-1">
                <span
                  className={cn(
                    'px-2 py-0.5 rounded text-xs',
                    tenant.is_active
                      ? 'bg-green-500/10 text-green-400'
                      : 'bg-red-500/10 text-red-400'
                  )}
                >
                  {tenant.is_active ? 'Active' : 'Inactive'}
                </span>
                <span className="flex items-center gap-1 text-sm text-[var(--sv-gray-400)]">
                  <Clock className="h-3 w-3" />
                  Created {formatDate(tenant.created_at)}
                </span>
              </div>
            </div>
          </div>
          <button
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg',
              'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)]',
              'text-[var(--sv-gray-400)] hover:text-white hover:bg-[var(--sv-gray-700)]',
              'transition-colors'
            )}
          >
            <Settings className="h-4 w-4" />
            Settings
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-4 mb-8">
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="flex items-center gap-2 text-[var(--sv-gray-400)] text-sm">
              <Users className="h-4 w-4" />
              Users
            </div>
            <div className="text-2xl font-bold text-white mt-1">
              {tenant.user_count || 0}
            </div>
          </div>
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="flex items-center gap-2 text-[var(--sv-gray-400)] text-sm">
              <MapPin className="h-4 w-4" />
              Sites
            </div>
            <div className="text-2xl font-bold text-white mt-1">
              {sites.length}
            </div>
          </div>
        </div>

        {/* Sites Section */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <MapPin className="h-5 w-5 text-[var(--sv-gray-400)]" />
              Sites
            </h2>
            <button
              onClick={() => setShowNewSiteForm(true)}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg',
                'bg-[var(--sv-primary)] text-white text-sm',
                'hover:bg-[var(--sv-primary-dark)] transition-colors'
              )}
            >
              <Plus className="h-4 w-4" />
              Add Site
            </button>
          </div>

          {/* New Site Form */}
          {showNewSiteForm && (
            <form
              onSubmit={handleCreateSite}
              className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4 mb-4"
            >
              <h3 className="text-white font-medium mb-3">New Site</h3>
              {siteError && (
                <div className="flex items-center gap-2 p-2 mb-3 rounded bg-red-500/10 text-red-400 text-sm">
                  <AlertCircle className="h-4 w-4" />
                  {siteError}
                </div>
              )}
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="block text-sm text-[var(--sv-gray-300)] mb-1">
                    Site Name *
                  </label>
                  <input
                    type="text"
                    value={newSiteName}
                    onChange={(e) => setNewSiteName(e.target.value)}
                    placeholder="Wien Depot"
                    required
                    className={cn(
                      'w-full px-3 py-2 rounded-lg text-sm',
                      'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                </div>
                <div>
                  <label className="block text-sm text-[var(--sv-gray-300)] mb-1">
                    Code (optional)
                  </label>
                  <input
                    type="text"
                    value={newSiteCode}
                    onChange={(e) => setNewSiteCode(e.target.value.toUpperCase())}
                    placeholder="WIE"
                    maxLength={10}
                    className={cn(
                      'w-full px-3 py-2 rounded-lg text-sm',
                      'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowNewSiteForm(false);
                    setNewSiteName('');
                    setNewSiteCode('');
                    setSiteError(null);
                  }}
                  className="px-3 py-1.5 text-sm text-[var(--sv-gray-400)] hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingSite || !newSiteName}
                  className={cn(
                    'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm',
                    'bg-[var(--sv-primary)] text-white',
                    'hover:bg-[var(--sv-primary-dark)] transition-colors',
                    'disabled:opacity-50'
                  )}
                >
                  {creatingSite ? (
                    <>
                      <div className="h-3 w-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Creating...
                    </>
                  ) : (
                    <>
                      <Check className="h-4 w-4" />
                      Create
                    </>
                  )}
                </button>
              </div>
            </form>
          )}

          {/* Sites List */}
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
            {sites.length === 0 ? (
              <div className="p-8 text-center text-[var(--sv-gray-400)]">
                No sites yet. Create your first site to get started.
              </div>
            ) : (
              <div className="divide-y divide-[var(--sv-gray-700)]">
                {sites.map((site) => (
                  <div
                    key={site.id}
                    className="flex items-center justify-between p-4 hover:bg-[var(--sv-gray-700)]/30 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-green-500/10">
                        <MapPin className="h-4 w-4 text-green-400" />
                      </div>
                      <div>
                        <div className="font-medium text-white">{site.name}</div>
                        <div className="flex items-center gap-2 text-sm text-[var(--sv-gray-400)]">
                          {site.code && (
                            <code className="px-1 py-0.5 rounded bg-[var(--sv-gray-700)] text-xs">
                              {site.code}
                            </code>
                          )}
                          <span className="text-xs">
                            Created {formatDate(site.created_at)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <h3 className="text-white font-medium mb-3">Quick Actions</h3>
          <div className="flex flex-wrap gap-2">
            {/* Set Active Context */}
            <button
              onClick={() => handleSetActiveContext(sites[0]?.id)}
              disabled={settingContext || contextSuccess}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm',
                contextSuccess
                  ? 'bg-green-500/10 text-green-400 border border-green-500/30'
                  : 'bg-[var(--sv-primary)] text-white hover:bg-[var(--sv-primary-dark)]',
                'transition-colors disabled:opacity-70'
              )}
            >
              {contextSuccess ? (
                <>
                  <CheckCircle className="h-4 w-4" />
                  Context Set!
                </>
              ) : settingContext ? (
                <>
                  <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Setting...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Set Active Context
                </>
              )}
            </button>
            <Link
              href={`/platform-admin/users/new?tenant=${tenantId}`}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm',
                'bg-[var(--sv-gray-700)] text-white',
                'hover:bg-[var(--sv-gray-600)] transition-colors'
              )}
            >
              <Users className="h-4 w-4" />
              Add User
            </Link>
          </div>
          {contextSuccess && (
            <p className="text-xs text-green-400 mt-2">
              Tenant context set. Page will reload to update navigation.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
