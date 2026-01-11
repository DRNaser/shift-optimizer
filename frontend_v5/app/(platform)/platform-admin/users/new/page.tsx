// =============================================================================
// SOLVEREIGN V4.5 - New User Page
// =============================================================================
// Create a new user with tenant/site/role binding.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { User, ArrowLeft, Check, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Tenant {
  id: number;
  name: string;
}

interface Site {
  id: number;
  tenant_id: number;
  name: string;
  code: string | null;
}

interface Role {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
}

export default function NewUserPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [dataLoading, setDataLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);

  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [tenantId, setTenantId] = useState<string>('');
  const [siteId, setSiteId] = useState<string>('');
  const [roleName, setRoleName] = useState<string>('dispatcher');

  useEffect(() => {
    async function loadData() {
      try {
        const [tenantsRes, rolesRes] = await Promise.all([
          fetch('/api/platform-admin/tenants'),
          fetch('/api/platform-admin/roles'),
        ]);

        if (!tenantsRes.ok || !rolesRes.ok) {
          throw new Error('Failed to load data');
        }

        setTenants(await tenantsRes.json());
        setRoles(await rolesRes.json());
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        setDataLoading(false);
      }
    }

    loadData();
  }, []);

  // Load sites when tenant changes
  useEffect(() => {
    async function loadSites() {
      if (!tenantId) {
        setSites([]);
        return;
      }

      try {
        const res = await fetch(`/api/platform-admin/tenants/${tenantId}/sites`);
        if (res.ok) {
          setSites(await res.json());
        }
      } catch (err) {
        console.error('Failed to load sites:', err);
      }
    }

    loadSites();
    setSiteId(''); // Reset site selection when tenant changes
  }, [tenantId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validation
    if (!email || !password || !tenantId || !roleName) {
      setError('Please fill in all required fields');
      return;
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    try {
      const res = await fetch('/api/platform-admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          display_name: displayName || undefined,
          password,
          tenant_id: parseInt(tenantId),
          site_id: siteId ? parseInt(siteId) : undefined,
          role_name: roleName,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || data.message || 'Failed to create user');
      }

      setSuccess(true);
      setTimeout(() => {
        router.push('/platform-admin/users');
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
    } finally {
      setLoading(false);
    }
  };

  // Filter roles - platform_admin should only be assignable by bootstrapping
  const availableRoles = roles.filter((r) => r.name !== 'platform_admin');

  if (dataLoading) {
    return (
      <div className="min-h-screen bg-[var(--sv-gray-900)] flex items-center justify-center">
        <div className="h-8 w-8 border-4 border-[var(--sv-primary)]/30 border-t-[var(--sv-primary)] rounded-full animate-spin" />
      </div>
    );
  }

  if (success) {
    return (
      <div className="min-h-screen bg-[var(--sv-gray-900)] flex items-center justify-center">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-500/10 mb-4">
            <Check className="h-8 w-8 text-green-400" />
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">User Created!</h2>
          <p className="text-[var(--sv-gray-400)]">Redirecting to users list...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-2 text-[var(--sv-gray-400)] hover:text-white mb-4"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <User className="h-6 w-6 text-[var(--sv-primary)]" />
            Create New User
          </h1>
          <p className="text-[var(--sv-gray-400)] mt-1">
            Add a new user with role assignment
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 p-3 mb-6 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400">
            <AlertCircle className="h-4 w-4" />
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-6 space-y-4">
          {/* Email */}
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Email Address *
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              required
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            />
          </div>

          {/* Display Name */}
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Display Name
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="John Smith"
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            />
          </div>

          {/* Password */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Password *
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 8 characters"
                  required
                  minLength={8}
                  className={cn(
                    'w-full px-3 py-2 pr-10 rounded-lg',
                    'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                    'text-white placeholder-[var(--sv-gray-500)]',
                    'focus:outline-none focus:border-[var(--sv-primary)]'
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--sv-gray-400)]"
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Confirm Password *
              </label>
              <input
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Repeat password"
                required
                className={cn(
                  'w-full px-3 py-2 rounded-lg',
                  'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                  'text-white placeholder-[var(--sv-gray-500)]',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
              />
            </div>
          </div>

          {/* Tenant */}
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Tenant *
            </label>
            <select
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              required
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                'text-white',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            >
              <option value="">Select tenant...</option>
              {tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
          </div>

          {/* Site (optional) */}
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Site (optional)
            </label>
            <select
              value={siteId}
              onChange={(e) => setSiteId(e.target.value)}
              disabled={!tenantId || sites.length === 0}
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                'text-white',
                'focus:outline-none focus:border-[var(--sv-primary)]',
                'disabled:opacity-50'
              )}
            >
              <option value="">All sites (tenant-wide)</option>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name} {site.code ? `(${site.code})` : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Role */}
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Role *
            </label>
            <select
              value={roleName}
              onChange={(e) => setRoleName(e.target.value)}
              required
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                'text-white',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            >
              {availableRoles.map((role) => (
                <option key={role.id} value={role.name}>
                  {role.display_name}
                </option>
              ))}
            </select>
            {roles.find((r) => r.name === roleName)?.description && (
              <p className="text-xs text-[var(--sv-gray-400)] mt-1">
                {roles.find((r) => r.name === roleName)?.description}
              </p>
            )}
          </div>

          {/* Submit */}
          <div className="pt-4">
            <button
              type="submit"
              disabled={loading}
              className={cn(
                'w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg',
                'bg-[var(--sv-primary)] text-white',
                'hover:bg-[var(--sv-primary-dark)] transition-colors',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              {loading ? (
                <>
                  <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Check className="h-4 w-4" />
                  Create User
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
