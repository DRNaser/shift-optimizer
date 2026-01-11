// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Permissions List
// =============================================================================
// View all permissions grouped by category.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { Key, Search, ChevronDown, ChevronRight, Copy, Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Permission {
  id: number;
  key: string;
  display_name: string;
  description: string | null;
  category: string | null;
}

interface ApiError {
  error_code?: string;
  message?: string;
  detail?: string;
}

export default function PermissionsListPage() {
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  useEffect(() => {
    async function loadPermissions() {
      try {
        const res = await fetch('/api/platform-admin/permissions');
        const data = await res.json();

        if (!res.ok) {
          setError({
            error_code: data.error_code || `HTTP_${res.status}`,
            message: data.message || data.detail || 'Failed to load permissions',
          });
          return;
        }

        setPermissions(data);
        // Expand all categories by default
        const categories = new Set<string>(data.map((p: Permission) => p.category || 'uncategorized'));
        setExpandedCategories(categories);
      } catch (err) {
        setError({
          error_code: 'NETWORK_ERROR',
          message: err instanceof Error ? err.message : 'Failed to load permissions',
        });
      } finally {
        setLoading(false);
      }
    }

    loadPermissions();
  }, []);

  const filteredPermissions = permissions.filter((perm) =>
    perm.key.toLowerCase().includes(searchQuery.toLowerCase()) ||
    perm.display_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Group by category
  const groupedPermissions = filteredPermissions.reduce((acc, perm) => {
    const category = perm.category || 'uncategorized';
    if (!acc[category]) acc[category] = [];
    acc[category].push(perm);
    return acc;
  }, {} as Record<string, Permission[]>);

  const toggleCategory = (category: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'platform': return 'text-purple-400 bg-purple-500/10';
      case 'tenant': return 'text-blue-400 bg-blue-500/10';
      case 'portal': return 'text-green-400 bg-green-500/10';
      default: return 'text-gray-400 bg-gray-500/10';
    }
  };

  const copyToClipboard = async (key: string) => {
    try {
      await navigator.clipboard.writeText(key);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Key className="h-6 w-6 text-[var(--sv-primary)]" />
              Permissions
            </h1>
            <p className="text-[var(--sv-gray-400)] mt-1">
              View all available permissions by category
            </p>
          </div>
          <div className="text-[var(--sv-gray-400)] text-sm">
            {permissions.length} permissions
          </div>
        </div>

        {/* Search */}
        <div className="mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--sv-gray-500)]" />
            <input
              type="text"
              placeholder="Search permissions..."
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
            <div className="text-red-400 font-medium">Failed to load permissions</div>
            <div className="text-red-400/80 text-sm mt-1">
              <span className="font-mono">{error.error_code}</span>: {error.message}
            </div>
            <div className="text-[var(--sv-gray-500)] text-xs mt-2 font-mono">
              GET /api/platform-admin/permissions
            </div>
          </div>
        )}

        {/* Permissions List */}
        {!loading && !error && (
          <div className="space-y-4">
            {Object.keys(groupedPermissions).length === 0 ? (
              <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-8 text-center text-[var(--sv-gray-400)]">
                {searchQuery ? 'No permissions match your search' : 'No permissions defined'}
              </div>
            ) : (
              Object.entries(groupedPermissions).sort(([a], [b]) => a.localeCompare(b)).map(([category, perms]) => (
                <div
                  key={category}
                  className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden"
                >
                  {/* Category Header */}
                  <button
                    onClick={() => toggleCategory(category)}
                    className="w-full flex items-center justify-between p-4 hover:bg-[var(--sv-gray-700)]/30 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      {expandedCategories.has(category) ? (
                        <ChevronDown className="h-4 w-4 text-[var(--sv-gray-400)]" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-[var(--sv-gray-400)]" />
                      )}
                      <span className={cn(
                        'px-2 py-0.5 rounded text-xs font-medium',
                        getCategoryColor(category)
                      )}>
                        {category}
                      </span>
                      <span className="text-[var(--sv-gray-400)] text-sm">
                        {perms.length} permission{perms.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </button>

                  {/* Permissions in Category */}
                  {expandedCategories.has(category) && (
                    <div className="border-t border-[var(--sv-gray-700)] divide-y divide-[var(--sv-gray-700)]/50">
                      {perms.map((perm) => (
                        <div key={perm.id} className="p-4 pl-12 group">
                          <div className="flex items-center gap-2">
                            <code className="text-sm text-white font-mono">{perm.key}</code>
                            <button
                              onClick={() => copyToClipboard(perm.key)}
                              className={cn(
                                'p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity',
                                copiedKey === perm.key
                                  ? 'text-green-400'
                                  : 'text-[var(--sv-gray-500)] hover:text-white hover:bg-[var(--sv-gray-700)]'
                              )}
                              title="Copy permission key"
                            >
                              {copiedKey === perm.key ? (
                                <Check className="h-3.5 w-3.5" />
                              ) : (
                                <Copy className="h-3.5 w-3.5" />
                              )}
                            </button>
                          </div>
                          <div className="text-sm text-[var(--sv-gray-400)] mt-1">
                            {perm.display_name}
                          </div>
                          {perm.description && (
                            <div className="text-xs text-[var(--sv-gray-500)] mt-1">
                              {perm.description}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
