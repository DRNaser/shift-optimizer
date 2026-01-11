// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Tenants List
// =============================================================================
// List and manage tenants.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Building2, Plus, Users, MapPin, ChevronRight, Search } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Tenant {
  id: number;
  name: string;
  is_active: boolean;
  created_at: string;
  user_count?: number;
  site_count?: number;
}

export default function TenantsListPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    async function loadTenants() {
      try {
        const res = await fetch('/api/platform-admin/tenants?include_counts=true');
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.message || 'Failed to load tenants');
        }
        const data = await res.json();
        setTenants(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load tenants');
      } finally {
        setLoading(false);
      }
    }

    loadTenants();
  }, []);

  const filteredTenants = tenants.filter((tenant) =>
    tenant.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Building2 className="h-6 w-6 text-[var(--sv-primary)]" />
              Tenants
            </h1>
            <p className="text-[var(--sv-gray-400)] mt-1">
              Manage tenant organizations and their configurations
            </p>
          </div>
          <Link
            href="/platform-admin/tenants/new"
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg',
              'bg-[var(--sv-primary)] text-white',
              'hover:bg-[var(--sv-primary-dark)] transition-colors'
            )}
          >
            <Plus className="h-4 w-4" />
            New Tenant
          </Link>
        </div>

        {/* Search */}
        <div className="mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--sv-gray-500)]" />
            <input
              type="text"
              placeholder="Search tenants..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={cn(
                'w-full pl-10 pr-4 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            />
          </div>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 border-4 border-[var(--sv-primary)]/30 border-t-[var(--sv-primary)] rounded-full animate-spin" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-400">
            {error}
          </div>
        )}

        {/* Tenants List */}
        {!loading && !error && (
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
            {filteredTenants.length === 0 ? (
              <div className="p-8 text-center text-[var(--sv-gray-400)]">
                {searchQuery ? 'No tenants match your search' : 'No tenants yet. Create your first tenant to get started.'}
              </div>
            ) : (
              <div className="divide-y divide-[var(--sv-gray-700)]">
                {filteredTenants.map((tenant) => (
                  <Link
                    key={tenant.id}
                    href={`/platform-admin/tenants/${tenant.id}`}
                    className="flex items-center justify-between p-4 hover:bg-[var(--sv-gray-700)]/50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className="p-2 rounded-lg bg-blue-500/10">
                        <Building2 className="h-5 w-5 text-blue-400" />
                      </div>
                      <div>
                        <h3 className="font-medium text-white">{tenant.name}</h3>
                        <div className="flex items-center gap-4 text-sm text-[var(--sv-gray-400)]">
                          <span className="flex items-center gap-1">
                            <Users className="h-3 w-3" />
                            {tenant.user_count || 0} users
                          </span>
                          <span className="flex items-center gap-1">
                            <MapPin className="h-3 w-3" />
                            {tenant.site_count || 0} sites
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span
                        className={cn(
                          'px-2 py-1 rounded text-xs',
                          tenant.is_active
                            ? 'bg-green-500/10 text-green-400'
                            : 'bg-red-500/10 text-red-400'
                        )}
                      >
                        {tenant.is_active ? 'Active' : 'Inactive'}
                      </span>
                      <ChevronRight className="h-4 w-4 text-[var(--sv-gray-500)]" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
