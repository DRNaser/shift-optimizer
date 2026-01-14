// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Users List
// =============================================================================
// List and manage users across all tenants.
// Uses Zod validation for type safety.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Users, Plus, Building2, Shield, Search, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ApiError } from '@/components/ui/api-error';
import {
  parseUserListResponse,
  parseTenantListResponse,
  type User,
  type Tenant,
} from '@/lib/schemas/platform-admin-schemas';

interface ApiErrorState {
  code: string;
  message: string;
  traceId?: string;
}

interface UserBinding {
  id?: number;
  tenant_id: number | null;
  site_id?: number | null;
  role_id?: number;
  role_name: string;
  is_active?: boolean;
}

export default function UsersListPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<ApiErrorState | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterTenant, setFilterTenant] = useState<string>('');

  useEffect(() => {
    async function loadData() {
      try {
        const [usersRes, tenantsRes] = await Promise.all([
          fetch('/api/platform-admin/users'),
          fetch('/api/platform-admin/tenants'),
        ]);

        // Handle 403 Forbidden explicitly
        if (usersRes.status === 403 || tenantsRes.status === 403) {
          const errorRes = usersRes.status === 403 ? usersRes : tenantsRes;
          const data = await errorRes.json();
          setApiError({
            code: data.error_code || 'FORBIDDEN',
            message: data.message || 'Access denied',
            traceId: data.trace_id,
          });
          return;
        }

        if (!usersRes.ok || !tenantsRes.ok) {
          throw new Error('Failed to load data');
        }

        const usersData = await usersRes.json();
        const tenantsData = await tenantsRes.json();

        // Zod validation for type safety
        setUsers(parseUserListResponse(usersData));
        setTenants(parseTenantListResponse(tenantsData));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load users');
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, []);

  const filteredUsers = users.filter((user) => {
    const matchesSearch =
      user.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (user.display_name?.toLowerCase() || '').includes(searchQuery.toLowerCase());
    const matchesTenant =
      !filterTenant ||
      user.bindings.some((b) => b.tenant_id === parseInt(filterTenant));
    return matchesSearch && matchesTenant;
  });

  const getRoleColor = (roleName: string) => {
    switch (roleName) {
      case 'platform_admin':
        return 'bg-purple-500/10 text-purple-400';
      case 'tenant_admin':
        return 'bg-blue-500/10 text-blue-400';
      case 'operator_admin':
        return 'bg-green-500/10 text-green-400';
      case 'dispatcher':
        return 'bg-yellow-500/10 text-yellow-400';
      default:
        return 'bg-gray-500/10 text-gray-400';
    }
  };

  const getTenantName = (tenantId: number) => {
    if (tenantId === 0) return 'Platform';
    const tenant = tenants.find((t) => t.id === tenantId);
    return tenant?.name || `Tenant #${tenantId}`;
  };

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Users className="h-6 w-6 text-[var(--sv-primary)]" />
              Users
            </h1>
            <p className="text-[var(--sv-gray-400)] mt-1">
              Manage users and their role assignments
            </p>
          </div>
          <Link
            href="/platform-admin/users/new"
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg',
              'bg-[var(--sv-primary)] text-white',
              'hover:bg-[var(--sv-primary-dark)] transition-colors'
            )}
          >
            <Plus className="h-4 w-4" />
            New User
          </Link>
        </div>

        {/* Filters */}
        <div className="flex gap-4 mb-6">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--sv-gray-500)]" />
            <input
              type="text"
              placeholder="Search users..."
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
          <select
            value={filterTenant}
            onChange={(e) => setFilterTenant(e.target.value)}
            className={cn(
              'px-4 py-2 rounded-lg',
              'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)]',
              'text-white',
              'focus:outline-none focus:border-[var(--sv-primary)]'
            )}
          >
            <option value="">All Tenants</option>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 border-4 border-[var(--sv-primary)]/30 border-t-[var(--sv-primary)] rounded-full animate-spin" />
          </div>
        )}

        {/* Access Denied State (403 Forbidden) */}
        {apiError && (
          <ApiError
            code={apiError.code}
            message={apiError.message}
            traceId={apiError.traceId}
            showBackLink={true}
            backHref="/platform-admin"
          />
        )}

        {/* Error State */}
        {!apiError && error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-400">
            {error}
          </div>
        )}

        {/* Users List */}
        {!loading && !error && !apiError && (
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
            {filteredUsers.length === 0 ? (
              <div className="p-8 text-center text-[var(--sv-gray-400)]">
                {searchQuery || filterTenant
                  ? 'No users match your filters'
                  : 'No users yet. Create your first user to get started.'}
              </div>
            ) : (
              <div className="divide-y divide-[var(--sv-gray-700)]">
                {filteredUsers.map((user) => (
                  <div
                    key={user.id}
                    className="flex items-center justify-between p-4 hover:bg-[var(--sv-gray-700)]/50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 rounded-full bg-[var(--sv-primary)]/10 flex items-center justify-center">
                        <span className="text-[var(--sv-primary)] font-medium">
                          {user.email[0].toUpperCase()}
                        </span>
                      </div>
                      <div>
                        <h3 className="font-medium text-white">
                          {user.display_name || user.email}
                        </h3>
                        <p className="text-sm text-[var(--sv-gray-400)]">{user.email}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {/* Bindings */}
                      <div className="flex flex-wrap gap-1">
                        {user.bindings.slice(0, 2).map((binding, idx) => (
                          <span
                            key={binding.id ?? `${user.id}-${binding.role_name}-${idx}`}
                            className={cn(
                              'px-2 py-0.5 rounded text-xs',
                              getRoleColor(binding.role_name)
                            )}
                          >
                            {binding.role_name.replace('_', ' ')}
                            <span className="opacity-60 ml-1">
                              @ {getTenantName(binding.tenant_id ?? 0)}
                            </span>
                          </span>
                        ))}
                        {user.bindings.length > 2 && (
                          <span className="px-2 py-0.5 rounded text-xs bg-[var(--sv-gray-700)] text-[var(--sv-gray-400)]">
                            +{user.bindings.length - 2} more
                          </span>
                        )}
                      </div>
                      {/* Status */}
                      <span
                        className={cn(
                          'px-2 py-1 rounded text-xs',
                          user.is_locked
                            ? 'bg-red-500/10 text-red-400'
                            : user.is_active
                            ? 'bg-green-500/10 text-green-400'
                            : 'bg-yellow-500/10 text-yellow-400'
                        )}
                      >
                        {user.is_locked ? 'Locked' : user.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
