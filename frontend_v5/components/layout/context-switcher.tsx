// =============================================================================
// SOLVEREIGN V4.6 - Platform Admin Context Switcher
// =============================================================================
// Tenant/Site context switching dropdown for platform admins.
// Only visible when user has role='platform_admin'.
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import { Building2, MapPin, X, ChevronDown, Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Tenant {
  id: number;
  name: string;
  is_active: boolean;
}

interface Site {
  id: number;
  tenant_id: number;
  name: string;
  code: string | null;
}

interface ContextSwitcherProps {
  activeTenantId?: number;
  activeSiteId?: number;
  activeTenantName?: string;
  activeSiteName?: string;
  onContextChange?: () => void;
  className?: string;
}

export function ContextSwitcher({
  activeTenantId,
  activeSiteId,
  activeTenantName,
  activeSiteName,
  onContextChange,
  className,
}: ContextSwitcherProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState<number | null>(activeTenantId ?? null);
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(activeSiteId ?? null);
  const [loading, setLoading] = useState(false);
  const [tenantSearch, setTenantSearch] = useState('');

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
    if (isOpen && tenants.length === 0) {
      fetchTenants();
    }
  }, [isOpen, tenants.length]);

  // Fetch sites when tenant changes
  useEffect(() => {
    async function fetchSites() {
      if (!selectedTenantId) {
        setSites([]);
        return;
      }
      try {
        const res = await fetch(`/api/platform-admin/tenants/${selectedTenantId}/sites`, {
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
  }, [selectedTenantId]);

  const handleSetContext = useCallback(async () => {
    if (!selectedTenantId) return;
    setLoading(true);
    try {
      const res = await fetch('/api/platform-admin/context', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: selectedTenantId,
          site_id: selectedSiteId,
        }),
      });
      if (res.ok) {
        setIsOpen(false);
        onContextChange?.();
      } else {
        console.error('Failed to set context');
      }
    } catch (err) {
      console.error('Error setting context:', err);
    } finally {
      setLoading(false);
    }
  }, [selectedTenantId, selectedSiteId, onContextChange]);

  const handleClearContext = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/platform-admin/context', {
        method: 'DELETE',
        credentials: 'include',
      });
      if (res.ok || res.status === 204) {
        setSelectedTenantId(null);
        setSelectedSiteId(null);
        setIsOpen(false);
        onContextChange?.();
      }
    } catch (err) {
      console.error('Error clearing context:', err);
    } finally {
      setLoading(false);
    }
  }, [onContextChange]);

  const filteredTenants = tenants.filter((t) =>
    t.name.toLowerCase().includes(tenantSearch.toLowerCase())
  );

  const hasActiveContext = activeTenantId !== undefined && activeTenantId !== null;

  return (
    <div className={cn('relative', className)}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'flex items-center gap-2 px-3 py-1.5 rounded-md transition-colors',
          hasActiveContext
            ? 'bg-[var(--sv-primary)]/20 border border-[var(--sv-primary)]/30 text-[var(--sv-primary)]'
            : 'bg-[var(--sv-error)]/20 border border-[var(--sv-error)]/30 text-[var(--sv-error)]'
        )}
      >
        <Building2 className="h-4 w-4" />
        <span className="text-sm font-medium">
          {hasActiveContext ? activeTenantName || `Tenant ${activeTenantId}` : 'Platform Admin'}
        </span>
        {hasActiveContext && activeSiteName && (
          <>
            <span className="text-xs opacity-60">/</span>
            <MapPin className="h-3 w-3 opacity-60" />
            <span className="text-sm opacity-80">{activeSiteName}</span>
          </>
        )}
        <ChevronDown className="h-4 w-4 ml-1" />
      </button>

      {/* Dropdown */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />

          {/* Panel */}
          <div className="absolute left-0 top-full mt-2 w-80 bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)] rounded-lg shadow-xl z-50">
            <div className="p-4 border-b border-[var(--sv-gray-700)]">
              <h3 className="text-sm font-semibold text-white mb-1">Switch Context</h3>
              <p className="text-xs text-[var(--sv-gray-400)]">
                Select a tenant to work with tenant-scoped features.
              </p>
            </div>

            {/* Tenant Selection */}
            <div className="p-3 border-b border-[var(--sv-gray-700)]">
              <label className="block text-xs font-medium text-[var(--sv-gray-400)] mb-2">
                Tenant
              </label>
              <input
                type="text"
                placeholder="Search tenants..."
                value={tenantSearch}
                onChange={(e) => setTenantSearch(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-[var(--sv-gray-900)] border border-[var(--sv-gray-700)] rounded-md text-white placeholder:text-[var(--sv-gray-500)] focus:outline-none focus:ring-1 focus:ring-[var(--sv-primary)]"
              />
              <div className="mt-2 max-h-40 overflow-y-auto">
                {filteredTenants.length === 0 ? (
                  <p className="text-xs text-[var(--sv-gray-500)] py-2">No tenants found</p>
                ) : (
                  filteredTenants.map((tenant) => (
                    <button
                      key={tenant.id}
                      type="button"
                      onClick={() => {
                        setSelectedTenantId(tenant.id);
                        setSelectedSiteId(null);
                      }}
                      className={cn(
                        'w-full flex items-center justify-between px-3 py-2 text-sm rounded-md transition-colors',
                        selectedTenantId === tenant.id
                          ? 'bg-[var(--sv-primary)] text-white'
                          : 'text-[var(--sv-gray-300)] hover:bg-[var(--sv-gray-700)]'
                      )}
                    >
                      <span>{tenant.name}</span>
                      {selectedTenantId === tenant.id && <Check className="h-4 w-4" />}
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* Site Selection (Optional) */}
            {selectedTenantId && sites.length > 0 && (
              <div className="p-3 border-b border-[var(--sv-gray-700)]">
                <label className="block text-xs font-medium text-[var(--sv-gray-400)] mb-2">
                  Site (Optional)
                </label>
                <div className="space-y-1">
                  <button
                    type="button"
                    onClick={() => setSelectedSiteId(null)}
                    className={cn(
                      'w-full flex items-center justify-between px-3 py-2 text-sm rounded-md transition-colors',
                      selectedSiteId === null
                        ? 'bg-[var(--sv-gray-600)] text-white'
                        : 'text-[var(--sv-gray-300)] hover:bg-[var(--sv-gray-700)]'
                    )}
                  >
                    <span className="italic">All Sites</span>
                    {selectedSiteId === null && <Check className="h-4 w-4" />}
                  </button>
                  {sites.map((site) => (
                    <button
                      key={site.id}
                      type="button"
                      onClick={() => setSelectedSiteId(site.id)}
                      className={cn(
                        'w-full flex items-center justify-between px-3 py-2 text-sm rounded-md transition-colors',
                        selectedSiteId === site.id
                          ? 'bg-[var(--sv-primary)] text-white'
                          : 'text-[var(--sv-gray-300)] hover:bg-[var(--sv-gray-700)]'
                      )}
                    >
                      <span>
                        {site.name}
                        {site.code && (
                          <span className="ml-2 text-xs opacity-60">({site.code})</span>
                        )}
                      </span>
                      {selectedSiteId === site.id && <Check className="h-4 w-4" />}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="p-3 flex items-center gap-2">
              {hasActiveContext && (
                <button
                  type="button"
                  onClick={handleClearContext}
                  disabled={loading}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm text-[var(--sv-gray-400)] hover:text-white hover:bg-[var(--sv-gray-700)] rounded-md transition-colors disabled:opacity-50"
                >
                  <X className="h-4 w-4" />
                  Clear
                </button>
              )}
              <button
                type="button"
                onClick={handleSetContext}
                disabled={!selectedTenantId || loading}
                className="flex-1 px-3 py-1.5 text-sm font-medium text-white bg-[var(--sv-primary)] hover:bg-[var(--sv-primary)]/80 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? 'Switching...' : 'Apply Context'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
