// =============================================================================
// SOLVEREIGN V4.6 - Tenant Picker Page
// =============================================================================
// Allows platform admins to select a tenant context before accessing
// tenant-scoped features like packs or portal.
// =============================================================================

'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Building2, MapPin, ArrowRight, Search, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePlatformUser } from '../layout-client';

interface Tenant {
  id: number;
  name: string;
  is_active: boolean;
  user_count?: number;
  site_count?: number;
}

interface Site {
  id: number;
  tenant_id: number;
  name: string;
  code: string | null;
}

export default function SelectTenantPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = searchParams.get('returnTo') || '/platform/home';
  const user = usePlatformUser();

  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [search, setSearch] = useState('');
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null);
  const [selectedSite, setSelectedSite] = useState<Site | null>(null);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<'tenant' | 'site'>('tenant');

  // Redirect non-platform-admins
  useEffect(() => {
    if (!user.isLoading && !user.is_platform_admin) {
      router.push('/platform/home');
    }
  }, [user, router]);

  // Fetch tenants on mount
  useEffect(() => {
    async function fetchTenants() {
      try {
        const res = await fetch('/api/platform-admin/tenants?include_counts=true', {
          credentials: 'include',
        });
        if (res.ok) {
          const data = await res.json();
          setTenants(data.filter((t: Tenant) => t.is_active));
        }
      } catch (err) {
        console.error('Failed to fetch tenants:', err);
      }
    }
    fetchTenants();
  }, []);

  // Fetch sites when tenant is selected
  useEffect(() => {
    async function fetchSites() {
      if (!selectedTenant) {
        setSites([]);
        return;
      }
      try {
        const res = await fetch(`/api/platform-admin/tenants/${selectedTenant.id}/sites`, {
          credentials: 'include',
        });
        if (res.ok) {
          const data = await res.json();
          setSites(data);
        }
      } catch (err) {
        console.error('Failed to fetch sites:', err);
      }
    }
    fetchSites();
  }, [selectedTenant]);

  const handleTenantSelect = (tenant: Tenant) => {
    setSelectedTenant(tenant);
    setSelectedSite(null);
    // If tenant has sites, show site selection step
    if (tenant.site_count && tenant.site_count > 0) {
      setStep('site');
    }
  };

  const handleConfirm = async () => {
    if (!selectedTenant) return;
    setLoading(true);
    try {
      const res = await fetch('/api/platform-admin/context', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: selectedTenant.id,
          site_id: selectedSite?.id,
        }),
      });
      if (res.ok) {
        await user.refetchUser();
        router.push(returnTo);
      } else {
        console.error('Failed to set context');
      }
    } catch (err) {
      console.error('Error setting context:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSkipContext = () => {
    router.push('/platform/home');
  };

  const filteredTenants = tenants.filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase())
  );

  if (user.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-[var(--sv-gray-400)]">Loading...</div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto py-8">
      {/* Header */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-[var(--sv-primary)]/20 mb-4">
          <Building2 className="h-8 w-8 text-[var(--sv-primary)]" />
        </div>
        <h1 className="text-2xl font-bold text-white mb-2">Select Working Context</h1>
        <p className="text-[var(--sv-gray-400)]">
          Choose a tenant to access tenant-scoped features.
        </p>
      </div>

      {/* Tenant Selection Step */}
      {step === 'tenant' && (
        <div className="bg-[var(--sv-gray-900)] border border-[var(--sv-gray-700)] rounded-lg overflow-hidden">
          {/* Search */}
          <div className="p-4 border-b border-[var(--sv-gray-700)]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--sv-gray-400)]" />
              <input
                type="text"
                placeholder="Search tenants..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)] rounded-md text-white placeholder:text-[var(--sv-gray-500)] focus:outline-none focus:ring-1 focus:ring-[var(--sv-primary)]"
              />
            </div>
          </div>

          {/* Tenant List */}
          <div className="max-h-[400px] overflow-y-auto">
            {filteredTenants.length === 0 ? (
              <div className="p-8 text-center text-[var(--sv-gray-500)]">
                No tenants found
              </div>
            ) : (
              filteredTenants.map((tenant) => (
                <button
                  key={tenant.id}
                  type="button"
                  onClick={() => handleTenantSelect(tenant)}
                  className={cn(
                    'w-full flex items-center justify-between px-4 py-3 text-left transition-colors',
                    'hover:bg-[var(--sv-gray-800)]',
                    selectedTenant?.id === tenant.id && 'bg-[var(--sv-primary)]/10'
                  )}
                >
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-lg bg-[var(--sv-gray-700)] flex items-center justify-center">
                      <Building2 className="h-5 w-5 text-[var(--sv-gray-400)]" />
                    </div>
                    <div>
                      <div className="font-medium text-white">{tenant.name}</div>
                      <div className="text-xs text-[var(--sv-gray-400)]">
                        {tenant.user_count ?? 0} users, {tenant.site_count ?? 0} sites
                      </div>
                    </div>
                  </div>
                  <ArrowRight className="h-5 w-5 text-[var(--sv-gray-500)]" />
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Site Selection Step */}
      {step === 'site' && selectedTenant && (
        <div className="bg-[var(--sv-gray-900)] border border-[var(--sv-gray-700)] rounded-lg overflow-hidden">
          {/* Header */}
          <div className="p-4 border-b border-[var(--sv-gray-700)] flex items-center gap-3">
            <button
              type="button"
              onClick={() => setStep('tenant')}
              className="p-1 rounded hover:bg-[var(--sv-gray-800)]"
            >
              <X className="h-4 w-4 text-[var(--sv-gray-400)]" />
            </button>
            <div>
              <div className="font-medium text-white">{selectedTenant.name}</div>
              <div className="text-xs text-[var(--sv-gray-400)]">Select a site (optional)</div>
            </div>
          </div>

          {/* Site List */}
          <div className="max-h-[300px] overflow-y-auto">
            {/* All Sites Option */}
            <button
              type="button"
              onClick={() => setSelectedSite(null)}
              className={cn(
                'w-full flex items-center justify-between px-4 py-3 text-left transition-colors',
                'hover:bg-[var(--sv-gray-800)]',
                selectedSite === null && 'bg-[var(--sv-primary)]/10'
              )}
            >
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-[var(--sv-gray-600)] flex items-center justify-center">
                  <MapPin className="h-5 w-5 text-[var(--sv-gray-300)]" />
                </div>
                <div>
                  <div className="font-medium text-white italic">All Sites</div>
                  <div className="text-xs text-[var(--sv-gray-400)]">
                    Access all sites in this tenant
                  </div>
                </div>
              </div>
            </button>

            {sites.map((site) => (
              <button
                key={site.id}
                type="button"
                onClick={() => setSelectedSite(site)}
                className={cn(
                  'w-full flex items-center justify-between px-4 py-3 text-left transition-colors',
                  'hover:bg-[var(--sv-gray-800)]',
                  selectedSite?.id === site.id && 'bg-[var(--sv-primary)]/10'
                )}
              >
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-[var(--sv-gray-700)] flex items-center justify-center">
                    <MapPin className="h-5 w-5 text-[var(--sv-gray-400)]" />
                  </div>
                  <div>
                    <div className="font-medium text-white">{site.name}</div>
                    {site.code && (
                      <div className="text-xs text-[var(--sv-gray-400)]">Code: {site.code}</div>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="mt-6 flex items-center justify-between">
        <button
          type="button"
          onClick={handleSkipContext}
          className="text-sm text-[var(--sv-gray-400)] hover:text-white transition-colors"
        >
          Continue without context
        </button>

        {selectedTenant && (
          <button
            type="button"
            onClick={handleConfirm}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary)]/80 transition-colors disabled:opacity-50"
          >
            {loading ? 'Setting context...' : 'Confirm Selection'}
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}
