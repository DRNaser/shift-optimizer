// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Tenants List (Redesigned)
// =============================================================================
// List and manage tenants with modern design system.
// Uses Zod validation for type safety.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Building2,
  Plus,
  Users,
  MapPin,
  ChevronRight,
  Search,
  Calendar,
  LayoutGrid,
  List,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/ui/spinner';
import { SkeletonTable } from '@/components/ui/skeleton';
import { ApiError } from '@/components/ui/api-error';
import { parseTenantListResponse, type Tenant } from '@/lib/schemas/platform-admin-schemas';

interface ApiErrorState {
  code: string;
  message: string;
  traceId?: string;
}

export default function TenantsListPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<ApiErrorState | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');

  useEffect(() => {
    async function loadTenants() {
      try {
        const res = await fetch('/api/platform-admin/tenants?include_counts=true');
        if (!res.ok) {
          const data = await res.json();
          // Handle 403 Forbidden explicitly
          if (res.status === 403) {
            setApiError({
              code: data.error_code || 'FORBIDDEN',
              message: data.message || 'Access denied',
              traceId: data.trace_id,
            });
            return;
          }
          throw new Error(data.message || 'Failed to load tenants');
        }
        const data = await res.json();
        // Zod validation for type safety
        const validated = parseTenantListResponse(data);
        setTenants(validated);
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
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto p-6 lg:p-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-xl bg-primary/10">
              <Building2 className="h-6 w-6 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">Tenants</h1>
              <p className="text-foreground-muted mt-0.5">
                Manage tenant organizations
              </p>
            </div>
          </div>
          <Button asChild leftIcon={<Plus className="h-4 w-4" />}>
            <Link href="/platform-admin/tenants/new">New Tenant</Link>
          </Button>
        </div>

        {/* Controls Bar */}
        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <div className="flex-1">
            <Input
              type="text"
              placeholder="Search tenants..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              leftIcon={<Search className="h-4 w-4" />}
            />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center border border-border rounded-lg p-1">
              <button
                onClick={() => setViewMode('list')}
                className={cn(
                  'p-2 rounded-md transition-colors',
                  viewMode === 'list'
                    ? 'bg-primary text-white'
                    : 'text-foreground-muted hover:text-foreground'
                )}
              >
                <List className="h-4 w-4" />
              </button>
              <button
                onClick={() => setViewMode('grid')}
                className={cn(
                  'p-2 rounded-md transition-colors',
                  viewMode === 'grid'
                    ? 'bg-primary text-white'
                    : 'text-foreground-muted hover:text-foreground'
                )}
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Results Count */}
        {!loading && !error && (
          <div className="mb-4">
            <p className="text-sm text-foreground-muted">
              {filteredTenants.length} {filteredTenants.length === 1 ? 'tenant' : 'tenants'}
              {searchQuery && ` matching "${searchQuery}"`}
            </p>
          </div>
        )}

        {/* Loading State */}
        {loading && <SkeletonTable rows={5} />}

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
          <Card variant="outline" className="border-error/30 bg-error-light p-6">
            <div className="flex items-center gap-3 text-error">
              <div className="p-2 rounded-full bg-error/10">
                <Building2 className="h-5 w-5" />
              </div>
              <div>
                <p className="font-medium">Failed to load tenants</p>
                <p className="text-sm opacity-80">{error}</p>
              </div>
            </div>
          </Card>
        )}

        {/* Empty State */}
        {!loading && !error && !apiError && filteredTenants.length === 0 && (
          <Card className="p-12 text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-muted mb-4">
              <Building2 className="h-8 w-8 text-foreground-muted" />
            </div>
            <h3 className="text-lg font-medium text-foreground mb-2">
              {searchQuery ? 'No tenants found' : 'No tenants yet'}
            </h3>
            <p className="text-foreground-muted mb-6 max-w-md mx-auto">
              {searchQuery
                ? 'Try adjusting your search to find what you\'re looking for.'
                : 'Create your first tenant to start managing organizations.'}
            </p>
            {!searchQuery && (
              <Button asChild leftIcon={<Plus className="h-4 w-4" />}>
                <Link href="/platform-admin/tenants/new">Create First Tenant</Link>
              </Button>
            )}
          </Card>
        )}

        {/* List View */}
        {!loading && !error && !apiError && filteredTenants.length > 0 && viewMode === 'list' && (
          <Card padding="none">
            <div className="divide-y divide-border">
              {filteredTenants.map((tenant, index) => (
                <Link
                  key={tenant.id}
                  href={`/platform-admin/tenants/${tenant.id}`}
                  className={cn(
                    'flex items-center justify-between p-4 hover:bg-card-hover transition-colors group',
                    index === 0 && 'rounded-t-xl',
                    index === filteredTenants.length - 1 && 'rounded-b-xl'
                  )}
                  style={{ animationDelay: `${index * 50}ms` }}
                >
                  <div className="flex items-center gap-4">
                    <div className="p-2.5 rounded-xl bg-primary/10 group-hover:bg-primary/15 transition-colors">
                      <Building2 className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-medium text-foreground group-hover:text-primary transition-colors">
                        {tenant.name}
                      </h3>
                      <div className="flex items-center gap-4 text-sm text-foreground-muted mt-1">
                        <span className="flex items-center gap-1.5">
                          <Users className="h-3.5 w-3.5" />
                          {tenant.user_count || 0} users
                        </span>
                        <span className="flex items-center gap-1.5">
                          <MapPin className="h-3.5 w-3.5" />
                          {tenant.site_count || 0} sites
                        </span>
                        <span className="flex items-center gap-1.5">
                          <Calendar className="h-3.5 w-3.5" />
                          {new Date(tenant.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <Badge variant={tenant.is_active ? 'success' : 'error'} dot>
                      {tenant.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                    <ChevronRight className="h-4 w-4 text-foreground-muted group-hover:translate-x-1 transition-transform" />
                  </div>
                </Link>
              ))}
            </div>
          </Card>
        )}

        {/* Grid View */}
        {!loading && !error && !apiError && filteredTenants.length > 0 && viewMode === 'grid' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 stagger-children">
            {filteredTenants.map((tenant) => (
              <Link key={tenant.id} href={`/platform-admin/tenants/${tenant.id}`}>
                <Card variant="interactive" className="h-full group">
                  <div className="flex items-start justify-between mb-4">
                    <div className="p-2.5 rounded-xl bg-primary/10 group-hover:bg-primary/15 transition-colors">
                      <Building2 className="h-5 w-5 text-primary" />
                    </div>
                    <Badge variant={tenant.is_active ? 'success' : 'error'} size="sm" dot>
                      {tenant.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </div>

                  <h3 className="font-semibold text-foreground group-hover:text-primary transition-colors mb-2">
                    {tenant.name}
                  </h3>

                  <div className="flex items-center gap-4 text-sm text-foreground-muted">
                    <span className="flex items-center gap-1.5">
                      <Users className="h-3.5 w-3.5" />
                      {tenant.user_count || 0}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <MapPin className="h-3.5 w-3.5" />
                      {tenant.site_count || 0}
                    </span>
                  </div>

                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-border">
                    <span className="text-xs text-foreground-muted">
                      Created {new Date(tenant.created_at).toLocaleDateString()}
                    </span>
                    <ChevronRight className="h-4 w-4 text-foreground-muted group-hover:translate-x-1 transition-transform" />
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
