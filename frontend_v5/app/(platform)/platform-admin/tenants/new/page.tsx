// =============================================================================
// SOLVEREIGN V4.6 - New Tenant Wizard
// =============================================================================
// Simple wizard for creating a new tenant with optional first site and admin.
// Features:
// - Structured error handling with field-level errors
// - Client-side validation with backend enforcement
// =============================================================================

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Building2, ArrowRight, ArrowLeft, Check, AlertCircle, MapPin, User } from 'lucide-react';
import { cn } from '@/lib/utils';

type Step = 'tenant' | 'site' | 'admin' | 'complete';

interface TenantData {
  name: string;
  ownerDisplayName: string;
}

interface SiteData {
  name: string;
  code: string;
  skip: boolean;
}

interface AdminData {
  email: string;
  displayName: string;
  password: string;
  confirmPassword: string;
  skip: boolean;
}

interface ApiError {
  code: string;
  message: string;
  field?: string;
  details?: {
    correlation_id?: string;
    [key: string]: unknown;
  };
}

/**
 * Parse API error response into structured error.
 * Handles formats:
 * - { error: { code, message, field?, details? } } (new normalized format)
 * - { detail: { code, message, field? } } (FastAPI HTTPException)
 * - { detail: string } (FastAPI string detail)
 * - { message: string } (generic)
 */
function parseApiError(data: unknown, fallbackMessage: string): ApiError {
  if (!data || typeof data !== 'object') {
    return { code: 'UNKNOWN_ERROR', message: fallbackMessage };
  }

  const obj = data as Record<string, unknown>;

  // New normalized format: { error: { code, message, field?, details? } }
  if (obj.error && typeof obj.error === 'object') {
    const err = obj.error as Record<string, unknown>;
    const details = err.details && typeof err.details === 'object'
      ? err.details as ApiError['details']
      : undefined;
    return {
      code: typeof err.code === 'string' ? err.code : 'UNKNOWN_ERROR',
      message: typeof err.message === 'string' ? err.message : fallbackMessage,
      field: typeof err.field === 'string' ? err.field : undefined,
      details,
    };
  }

  // FastAPI HTTPException with structured detail
  if (obj.detail && typeof obj.detail === 'object' && !Array.isArray(obj.detail)) {
    const detail = obj.detail as Record<string, unknown>;
    return {
      code: typeof detail.code === 'string' ? detail.code : 'API_ERROR',
      message: typeof detail.message === 'string' ? detail.message : fallbackMessage,
      field: typeof detail.field === 'string' ? detail.field : undefined,
    };
  }

  // FastAPI HTTPException with string detail
  if (typeof obj.detail === 'string') {
    return { code: 'API_ERROR', message: obj.detail };
  }

  // Pydantic validation errors
  if (Array.isArray(obj.detail) && obj.detail.length > 0) {
    const firstError = obj.detail[0] as Record<string, unknown>;
    if (firstError && firstError.msg) {
      const loc = firstError.loc as unknown[];
      const field = loc && loc.length > 0 ? String(loc[loc.length - 1]) : undefined;
      return {
        code: 'VALIDATION_FAILED',
        message: String(firstError.msg),
        field: field !== 'body' ? field : undefined,
      };
    }
  }

  // Generic message
  if (typeof obj.message === 'string') {
    return { code: 'API_ERROR', message: obj.message };
  }

  return { code: 'UNKNOWN_ERROR', message: fallbackMessage };
}

export default function NewTenantWizard() {
  const router = useRouter();
  const [step, setStep] = useState<Step>('tenant');
  const [loading, setLoading] = useState(false);

  // Banner error (always shown at top)
  const [bannerError, setBannerError] = useState<string | null>(null);
  // Error code for debugging
  const [errorCode, setErrorCode] = useState<string | null>(null);

  // Field-level errors
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const [tenantData, setTenantData] = useState<TenantData>({ name: '', ownerDisplayName: '' });
  const [siteData, setSiteData] = useState<SiteData>({ name: '', code: '', skip: false });
  const [adminData, setAdminData] = useState<AdminData>({
    email: '',
    displayName: '',
    password: '',
    confirmPassword: '',
    skip: false,
  });

  const [createdTenantId, setCreatedTenantId] = useState<number | null>(null);
  const [createdSiteId, setCreatedSiteId] = useState<number | null>(null);

  // Clear field error when user starts typing
  const clearFieldError = (field: string) => {
    if (fieldErrors[field]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  // Set error from API response
  const setApiError = (error: ApiError) => {
    setBannerError(error.message);
    setErrorCode(error.code);
    if (error.field) {
      setFieldErrors({ [error.field]: error.message });
    } else {
      setFieldErrors({});
    }
  };

  // Clear all errors
  const clearErrors = () => {
    setBannerError(null);
    setErrorCode(null);
    setFieldErrors({});
  };

  // Client-side validation for tenant name
  const validateTenantName = (name: string): string | null => {
    if (name.length < 2) {
      return 'Name must be at least 2 characters';
    }
    if (name.length > 100) {
      return 'Name must be at most 100 characters';
    }
    // Match backend regex: alphanumeric, spaces, hyphens, underscores, dots
    const pattern = /^[\w\s\-\.]+$/u;
    if (!pattern.test(name)) {
      return 'Name can only contain letters, numbers, spaces, hyphens, underscores, and dots';
    }
    return null;
  };

  const handleCreateTenant = async () => {
    clearErrors();

    // Client-side validation
    const nameError = validateTenantName(tenantData.name);
    if (nameError) {
      setFieldErrors({ name: nameError });
      setBannerError(nameError);
      return;
    }

    setLoading(true);

    try {
      const res = await fetch('/api/platform-admin/tenants', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: tenantData.name,
          owner_display_name: tenantData.ownerDisplayName || undefined,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const error = parseApiError(data, 'Failed to create tenant');
        setApiError(error);
        return;
      }

      setCreatedTenantId(data.id);
      setStep('site');
    } catch (err) {
      setBannerError(err instanceof Error ? err.message : 'Failed to create tenant');
      setErrorCode('NETWORK_ERROR');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateSite = async () => {
    if (siteData.skip) {
      setStep('admin');
      return;
    }

    if (!createdTenantId) return;

    clearErrors();
    setLoading(true);

    try {
      const res = await fetch(`/api/platform-admin/tenants/${createdTenantId}/sites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: siteData.name,
          code: siteData.code || undefined,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const error = parseApiError(data, 'Failed to create site');
        setApiError(error);
        return;
      }

      setCreatedSiteId(data.id);
      setStep('admin');
    } catch (err) {
      setBannerError(err instanceof Error ? err.message : 'Failed to create site');
      setErrorCode('NETWORK_ERROR');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateAdmin = async () => {
    if (adminData.skip) {
      setStep('complete');
      return;
    }

    if (!createdTenantId) return;

    clearErrors();

    // Client-side validation
    if (adminData.password !== adminData.confirmPassword) {
      setFieldErrors({ confirmPassword: 'Passwords do not match' });
      setBannerError('Passwords do not match');
      return;
    }

    if (adminData.password.length < 8) {
      setFieldErrors({ password: 'Password must be at least 8 characters' });
      setBannerError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    try {
      const res = await fetch('/api/platform-admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: adminData.email,
          display_name: adminData.displayName || undefined,
          password: adminData.password,
          tenant_id: createdTenantId,
          site_id: createdSiteId,
          role_name: 'tenant_admin',
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const error = parseApiError(data, 'Failed to create admin user');
        setApiError(error);
        return;
      }

      setStep('complete');
    } catch (err) {
      setBannerError(err instanceof Error ? err.message : 'Failed to create admin user');
      setErrorCode('NETWORK_ERROR');
    } finally {
      setLoading(false);
    }
  };

  const steps: { key: Step; label: string; icon: typeof Building2 }[] = [
    { key: 'tenant', label: 'Tenant', icon: Building2 },
    { key: 'site', label: 'Site', icon: MapPin },
    { key: 'admin', label: 'Admin', icon: User },
    { key: 'complete', label: 'Done', icon: Check },
  ];

  const currentStepIndex = steps.findIndex((s) => s.key === step);

  // Input class with optional error state
  const inputClass = (hasError: boolean, disabled?: boolean) =>
    cn(
      'w-full px-3 py-2 rounded-lg',
      'bg-[var(--sv-gray-900)] text-white placeholder-[var(--sv-gray-500)]',
      'focus:outline-none',
      hasError
        ? 'border-2 border-red-500 focus:border-red-500'
        : 'border border-[var(--sv-gray-600)] focus:border-[var(--sv-primary)]',
      disabled && 'opacity-50'
    );

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-white">Create New Tenant</h1>
          <p className="text-[var(--sv-gray-400)] mt-1">
            Set up a new tenant organization with optional site and admin user
          </p>
        </div>

        {/* Progress Steps */}
        <div className="flex items-center gap-2 mb-8">
          {steps.map((s, i) => (
            <div key={s.key} className="flex items-center">
              <div
                className={cn(
                  'flex items-center gap-2 px-3 py-1.5 rounded-full text-sm',
                  i <= currentStepIndex
                    ? 'bg-[var(--sv-primary)]/10 text-[var(--sv-primary)]'
                    : 'bg-[var(--sv-gray-800)] text-[var(--sv-gray-500)]'
                )}
              >
                <s.icon className="h-4 w-4" />
                <span className="hidden sm:inline">{s.label}</span>
              </div>
              {i < steps.length - 1 && (
                <ArrowRight className="h-4 w-4 mx-2 text-[var(--sv-gray-600)]" />
              )}
            </div>
          ))}
        </div>

        {/* Banner Error Message */}
        {bannerError && (
          <div className="flex items-start gap-2 p-3 mb-6 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <span>{bannerError}</span>
              {errorCode && errorCode !== 'UNKNOWN_ERROR' && (
                <span className="ml-2 text-xs text-red-400/60">({errorCode})</span>
              )}
            </div>
          </div>
        )}

        {/* Step Content */}
        <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-6">
          {/* Step 1: Tenant Details */}
          {step === 'tenant' && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-white">Tenant Details</h2>
              <div>
                <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                  Tenant Name *
                </label>
                <input
                  type="text"
                  value={tenantData.name}
                  onChange={(e) => {
                    setTenantData({ ...tenantData, name: e.target.value });
                    clearFieldError('name');
                  }}
                  placeholder="Acme Corporation"
                  className={inputClass(!!fieldErrors.name)}
                />
                {fieldErrors.name && (
                  <p className="mt-1 text-sm text-red-400">{fieldErrors.name}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                  Owner / Contact Name (optional)
                </label>
                <input
                  type="text"
                  value={tenantData.ownerDisplayName}
                  onChange={(e) => setTenantData({ ...tenantData, ownerDisplayName: e.target.value })}
                  placeholder="John Smith"
                  className={inputClass(false)}
                />
              </div>
              <div className="flex justify-end pt-4">
                <button
                  onClick={handleCreateTenant}
                  disabled={!tenantData.name || loading}
                  className={cn(
                    'flex items-center gap-2 px-4 py-2 rounded-lg',
                    'bg-[var(--sv-primary)] text-white',
                    'hover:bg-[var(--sv-primary-dark)] transition-colors',
                    'disabled:opacity-50 disabled:cursor-not-allowed'
                  )}
                >
                  {loading ? 'Creating...' : 'Create Tenant'}
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* Step 2: Site (Optional) */}
          {step === 'site' && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-white">Add First Site (Optional)</h2>
              <p className="text-sm text-[var(--sv-gray-400)]">
                Create the first site for this tenant. You can skip this step and add sites later.
              </p>
              <div>
                <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                  Site Name
                </label>
                <input
                  type="text"
                  value={siteData.name}
                  onChange={(e) => {
                    setSiteData({ ...siteData, name: e.target.value });
                    clearFieldError('name');
                  }}
                  placeholder="Wien Depot"
                  disabled={siteData.skip}
                  className={inputClass(!!fieldErrors.name, siteData.skip)}
                />
                {fieldErrors.name && (
                  <p className="mt-1 text-sm text-red-400">{fieldErrors.name}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                  Site Code (optional, auto-generated)
                </label>
                <input
                  type="text"
                  value={siteData.code}
                  onChange={(e) => {
                    setSiteData({ ...siteData, code: e.target.value.toUpperCase() });
                    clearFieldError('code');
                  }}
                  placeholder="WIE"
                  maxLength={10}
                  disabled={siteData.skip}
                  className={inputClass(!!fieldErrors.code, siteData.skip)}
                />
                {fieldErrors.code && (
                  <p className="mt-1 text-sm text-red-400">{fieldErrors.code}</p>
                )}
              </div>
              <label className="flex items-center gap-2 text-sm text-[var(--sv-gray-400)]">
                <input
                  type="checkbox"
                  checked={siteData.skip}
                  onChange={(e) => setSiteData({ ...siteData, skip: e.target.checked })}
                  className="rounded"
                />
                Skip this step
              </label>
              <div className="flex justify-between pt-4">
                <button
                  onClick={() => { clearErrors(); setStep('tenant'); }}
                  className="flex items-center gap-2 px-4 py-2 text-[var(--sv-gray-400)] hover:text-white"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Back
                </button>
                <button
                  onClick={handleCreateSite}
                  disabled={(!siteData.name && !siteData.skip) || loading}
                  className={cn(
                    'flex items-center gap-2 px-4 py-2 rounded-lg',
                    'bg-[var(--sv-primary)] text-white',
                    'hover:bg-[var(--sv-primary-dark)] transition-colors',
                    'disabled:opacity-50 disabled:cursor-not-allowed'
                  )}
                >
                  {loading ? 'Creating...' : siteData.skip ? 'Skip' : 'Create Site'}
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* Step 3: Admin User (Optional) */}
          {step === 'admin' && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-white">Add Tenant Admin (Optional)</h2>
              <p className="text-sm text-[var(--sv-gray-400)]">
                Create the first tenant administrator. This user will have full access to manage the tenant.
              </p>
              <div>
                <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  value={adminData.email}
                  onChange={(e) => {
                    setAdminData({ ...adminData, email: e.target.value });
                    clearFieldError('email');
                  }}
                  placeholder="admin@example.com"
                  disabled={adminData.skip}
                  className={inputClass(!!fieldErrors.email, adminData.skip)}
                />
                {fieldErrors.email && (
                  <p className="mt-1 text-sm text-red-400">{fieldErrors.email}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                  Display Name (optional)
                </label>
                <input
                  type="text"
                  value={adminData.displayName}
                  onChange={(e) => setAdminData({ ...adminData, displayName: e.target.value })}
                  placeholder="John Smith"
                  disabled={adminData.skip}
                  className={inputClass(false, adminData.skip)}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Password
                  </label>
                  <input
                    type="password"
                    value={adminData.password}
                    onChange={(e) => {
                      setAdminData({ ...adminData, password: e.target.value });
                      clearFieldError('password');
                    }}
                    placeholder="Min 8 characters"
                    disabled={adminData.skip}
                    className={inputClass(!!fieldErrors.password, adminData.skip)}
                  />
                  {fieldErrors.password && (
                    <p className="mt-1 text-sm text-red-400">{fieldErrors.password}</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Confirm Password
                  </label>
                  <input
                    type="password"
                    value={adminData.confirmPassword}
                    onChange={(e) => {
                      setAdminData({ ...adminData, confirmPassword: e.target.value });
                      clearFieldError('confirmPassword');
                    }}
                    placeholder="Repeat password"
                    disabled={adminData.skip}
                    className={inputClass(!!fieldErrors.confirmPassword, adminData.skip)}
                  />
                  {fieldErrors.confirmPassword && (
                    <p className="mt-1 text-sm text-red-400">{fieldErrors.confirmPassword}</p>
                  )}
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-[var(--sv-gray-400)]">
                <input
                  type="checkbox"
                  checked={adminData.skip}
                  onChange={(e) => setAdminData({ ...adminData, skip: e.target.checked })}
                  className="rounded"
                />
                Skip this step
              </label>
              <div className="flex justify-between pt-4">
                <button
                  onClick={() => { clearErrors(); setStep('site'); }}
                  className="flex items-center gap-2 px-4 py-2 text-[var(--sv-gray-400)] hover:text-white"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Back
                </button>
                <button
                  onClick={handleCreateAdmin}
                  disabled={(!adminData.email && !adminData.skip) || (!adminData.password && !adminData.skip) || loading}
                  className={cn(
                    'flex items-center gap-2 px-4 py-2 rounded-lg',
                    'bg-[var(--sv-primary)] text-white',
                    'hover:bg-[var(--sv-primary-dark)] transition-colors',
                    'disabled:opacity-50 disabled:cursor-not-allowed'
                  )}
                >
                  {loading ? 'Creating...' : adminData.skip ? 'Finish' : 'Create Admin'}
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* Step 4: Complete */}
          {step === 'complete' && (
            <div className="text-center py-8">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-500/10 mb-4">
                <Check className="h-8 w-8 text-green-400" />
              </div>
              <h2 className="text-xl font-semibold text-white mb-2">Tenant Created Successfully!</h2>
              <p className="text-[var(--sv-gray-400)] mb-6">
                {tenantData.name} has been set up and is ready to use.
              </p>
              <div className="flex justify-center gap-4">
                <button
                  onClick={() => router.push('/platform-admin/tenants')}
                  className={cn(
                    'px-4 py-2 rounded-lg',
                    'bg-[var(--sv-gray-700)] text-white',
                    'hover:bg-[var(--sv-gray-600)] transition-colors'
                  )}
                >
                  View All Tenants
                </button>
                <button
                  onClick={() => router.push(`/platform-admin/tenants/${createdTenantId}`)}
                  className={cn(
                    'px-4 py-2 rounded-lg',
                    'bg-[var(--sv-primary)] text-white',
                    'hover:bg-[var(--sv-primary-dark)] transition-colors'
                  )}
                >
                  View Tenant Details
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
