// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Roles List
// =============================================================================
// View roles and their permissions.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { Shield, ChevronRight, Search, Key } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

interface Role {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  is_system: boolean;
}

interface ApiError {
  error_code?: string;
  message?: string;
  detail?: string;
}

export default function RolesListPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    async function loadRoles() {
      try {
        const res = await fetch('/api/platform-admin/roles');
        const data = await res.json();

        if (!res.ok) {
          setError({
            error_code: data.error_code || `HTTP_${res.status}`,
            message: data.message || data.detail || 'Failed to load roles',
          });
          return;
        }

        setRoles(data);
      } catch (err) {
        setError({
          error_code: 'NETWORK_ERROR',
          message: err instanceof Error ? err.message : 'Failed to load roles',
        });
      } finally {
        setLoading(false);
      }
    }

    loadRoles();
  }, []);

  const filteredRoles = roles.filter((role) =>
    role.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    role.display_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Shield className="h-6 w-6 text-[var(--sv-primary)]" />
              Roles
            </h1>
            <p className="text-[var(--sv-gray-400)] mt-1">
              View system roles and their permissions
            </p>
          </div>
        </div>

        {/* Search */}
        <div className="mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--sv-gray-500)]" />
            <input
              type="text"
              placeholder="Search roles..."
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
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
            <div className="text-red-400 font-medium">Failed to load roles</div>
            <div className="text-red-400/80 text-sm mt-1">
              <span className="font-mono">{error.error_code}</span>: {error.message}
            </div>
            <div className="text-[var(--sv-gray-500)] text-xs mt-2 font-mono">
              GET /api/platform-admin/roles
            </div>
          </div>
        )}

        {/* Roles List */}
        {!loading && !error && (
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
            {filteredRoles.length === 0 ? (
              <div className="p-8 text-center text-[var(--sv-gray-400)]">
                {searchQuery ? 'No roles match your search' : 'No roles defined'}
              </div>
            ) : (
              <div className="divide-y divide-[var(--sv-gray-700)]">
                {filteredRoles.map((role) => (
                  <Link
                    key={role.id}
                    href={`/platform-admin/roles/${role.name}`}
                    className="flex items-center justify-between p-4 hover:bg-[var(--sv-gray-700)]/50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className={cn(
                        'p-2 rounded-lg',
                        role.name === 'platform_admin' ? 'bg-purple-500/10' :
                        role.name === 'tenant_admin' ? 'bg-blue-500/10' :
                        'bg-green-500/10'
                      )}>
                        <Shield className={cn(
                          'h-5 w-5',
                          role.name === 'platform_admin' ? 'text-purple-400' :
                          role.name === 'tenant_admin' ? 'text-blue-400' :
                          'text-green-400'
                        )} />
                      </div>
                      <div>
                        <h3 className="font-medium text-white">{role.display_name}</h3>
                        <div className="flex items-center gap-2 text-sm text-[var(--sv-gray-400)]">
                          <span className="font-mono text-xs">{role.name}</span>
                          {role.is_system && (
                            <span className="px-1.5 py-0.5 rounded text-xs bg-[var(--sv-gray-700)] text-[var(--sv-gray-400)]">
                              system
                            </span>
                          )}
                        </div>
                        {role.description && (
                          <p className="text-xs text-[var(--sv-gray-500)] mt-1">{role.description}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Key className="h-4 w-4 text-[var(--sv-gray-500)]" />
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
