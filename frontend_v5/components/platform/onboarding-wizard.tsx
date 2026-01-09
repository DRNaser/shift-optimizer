// =============================================================================
// SOLVEREIGN Platform Admin - Onboarding Wizard
// =============================================================================
// Step-by-step wizard for creating first Organization → Tenant → Site.
// =============================================================================

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Building2,
  Building,
  MapPin,
  Package,
  ArrowRight,
  ArrowLeft,
  CheckCircle,
  Rocket,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface OnboardingWizardProps {
  onComplete: () => void;
}

type Step = 'welcome' | 'organization' | 'tenant' | 'site' | 'entitlements' | 'complete';

interface WizardData {
  org: {
    org_code: string;
    name: string;
  };
  tenant: {
    tenant_code: string;
    name: string;
  };
  site: {
    site_code: string;
    name: string;
    timezone: string;
  };
  entitlements: string[];
}

const STEPS: { id: Step; label: string; icon: React.ElementType }[] = [
  { id: 'organization', label: 'Organization', icon: Building2 },
  { id: 'tenant', label: 'Tenant', icon: Building },
  { id: 'site', label: 'Site', icon: MapPin },
  { id: 'entitlements', label: 'Packs', icon: Package },
];

const AVAILABLE_PACKS = [
  {
    id: 'shift-optimizer',
    name: 'Shift Optimizer',
    description: 'Automated driver scheduling with compliance audits',
  },
  {
    id: 'routing',
    name: 'Routing Pack',
    description: 'VRPTW route optimization with OSRM/OR-Tools',
  },
];

export function OnboardingWizard({ onComplete }: OnboardingWizardProps) {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState<Step>('welcome');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdOrgCode, setCreatedOrgCode] = useState<string | null>(null);
  const [createdTenantCode, setCreatedTenantCode] = useState<string | null>(null);

  const [data, setData] = useState<WizardData>({
    org: { org_code: '', name: '' },
    tenant: { tenant_code: 'production', name: 'Production' },
    site: { site_code: 'main', name: 'Main Site', timezone: 'Europe/Berlin' },
    entitlements: ['shift-optimizer'],
  });

  const getCurrentStepIndex = () => {
    return STEPS.findIndex((s) => s.id === currentStep);
  };

  const handleNext = async () => {
    setError(null);

    switch (currentStep) {
      case 'welcome':
        setCurrentStep('organization');
        break;

      case 'organization':
        // Create organization
        setSubmitting(true);
        try {
          const res = await fetch('/api/platform/orgs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data.org),
          });

          if (!res.ok) {
            const errorData = await res.json();
            throw new Error(errorData.error?.message || 'Failed to create organization');
          }

          setCreatedOrgCode(data.org.org_code);
          setCurrentStep('tenant');
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
          setSubmitting(false);
        }
        break;

      case 'tenant':
        // Create tenant
        if (!createdOrgCode) {
          setError('Organization not created');
          return;
        }
        setSubmitting(true);
        try {
          const res = await fetch(`/api/platform/orgs/${createdOrgCode}/tenants`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data.tenant),
          });

          if (!res.ok) {
            const errorData = await res.json();
            throw new Error(errorData.error?.message || 'Failed to create tenant');
          }

          setCreatedTenantCode(data.tenant.tenant_code);
          setCurrentStep('site');
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
          setSubmitting(false);
        }
        break;

      case 'site':
        // Create site
        if (!createdTenantCode) {
          setError('Tenant not created');
          return;
        }
        setSubmitting(true);
        try {
          const res = await fetch(`/api/platform/tenants/${createdTenantCode}/sites`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data.site),
          });

          if (!res.ok) {
            const errorData = await res.json();
            throw new Error(errorData.error?.message || 'Failed to create site');
          }

          setCurrentStep('entitlements');
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
          setSubmitting(false);
        }
        break;

      case 'entitlements':
        // Enable selected packs
        if (!createdTenantCode) {
          setError('Tenant not created');
          return;
        }
        setSubmitting(true);
        try {
          await Promise.all(
            data.entitlements.map((packId) =>
              fetch(`/api/platform/tenants/${createdTenantCode}/entitlements/${packId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_enabled: true }),
              })
            )
          );

          setCurrentStep('complete');
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
          setSubmitting(false);
        }
        break;

      case 'complete':
        onComplete();
        router.push(`/platform/orgs/${createdOrgCode}`);
        break;
    }
  };

  const handleBack = () => {
    switch (currentStep) {
      case 'organization':
        setCurrentStep('welcome');
        break;
      case 'tenant':
        setCurrentStep('organization');
        break;
      case 'site':
        setCurrentStep('tenant');
        break;
      case 'entitlements':
        setCurrentStep('site');
        break;
    }
  };

  const toggleEntitlement = (packId: string) => {
    setData((prev) => ({
      ...prev,
      entitlements: prev.entitlements.includes(packId)
        ? prev.entitlements.filter((id) => id !== packId)
        : [...prev.entitlements, packId],
    }));
  };

  return (
    <div className="min-h-[80vh] flex flex-col items-center justify-center">
      <div className="w-full max-w-2xl">
        {/* Progress Steps */}
        {currentStep !== 'welcome' && currentStep !== 'complete' && (
          <div className="mb-8">
            <div className="flex items-center justify-between">
              {STEPS.map((step, index) => {
                const isActive = step.id === currentStep;
                const isPast = getCurrentStepIndex() > index;
                const StepIcon = step.icon;

                return (
                  <div key={step.id} className="flex items-center">
                    <div className="flex flex-col items-center">
                      <div
                        className={cn(
                          'h-10 w-10 rounded-full flex items-center justify-center border-2 transition-colors',
                          isPast
                            ? 'bg-green-500 border-green-500 text-white'
                            : isActive
                            ? 'bg-[var(--sv-primary)] border-[var(--sv-primary)] text-white'
                            : 'bg-[var(--sv-gray-800)] border-[var(--sv-gray-600)] text-[var(--sv-gray-500)]'
                        )}
                      >
                        {isPast ? (
                          <CheckCircle className="h-5 w-5" />
                        ) : (
                          <StepIcon className="h-5 w-5" />
                        )}
                      </div>
                      <span
                        className={cn(
                          'text-xs mt-2',
                          isActive ? 'text-white' : 'text-[var(--sv-gray-500)]'
                        )}
                      >
                        {step.label}
                      </span>
                    </div>
                    {index < STEPS.length - 1 && (
                      <div
                        className={cn(
                          'w-16 h-0.5 mx-2',
                          isPast ? 'bg-green-500' : 'bg-[var(--sv-gray-700)]'
                        )}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Card */}
        <div className="bg-[var(--sv-gray-900)] rounded-xl border border-[var(--sv-gray-700)] p-8">
          {/* Welcome Step */}
          {currentStep === 'welcome' && (
            <div className="text-center">
              <div className="h-20 w-20 rounded-2xl bg-[var(--sv-primary)]/10 flex items-center justify-center mx-auto mb-6">
                <Rocket className="h-10 w-10 text-[var(--sv-primary)]" />
              </div>
              <h1 className="text-2xl font-bold text-white mb-3">Welcome to SOLVEREIGN</h1>
              <p className="text-[var(--sv-gray-400)] mb-8 max-w-md mx-auto">
                Let&apos;s set up your first customer. This wizard will guide you through creating an
                organization, tenant, site, and enabling packs.
              </p>
              <button
                onClick={handleNext}
                className={cn(
                  'inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium',
                  'bg-[var(--sv-primary)] text-white',
                  'hover:bg-[var(--sv-primary-dark)] transition-colors'
                )}
              >
                Get Started
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          )}

          {/* Organization Step */}
          {currentStep === 'organization' && (
            <div>
              <div className="flex items-center gap-3 mb-6">
                <div className="h-12 w-12 rounded-xl bg-[var(--sv-primary)]/10 flex items-center justify-center">
                  <Building2 className="h-6 w-6 text-[var(--sv-primary)]" />
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-white">Create Organization</h2>
                  <p className="text-sm text-[var(--sv-gray-400)]">
                    Organizations represent your customers
                  </p>
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Organization Code
                  </label>
                  <input
                    type="text"
                    value={data.org.org_code}
                    onChange={(e) =>
                      setData((prev) => ({
                        ...prev,
                        org: {
                          ...prev.org,
                          org_code: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''),
                        },
                      }))
                    }
                    placeholder="e.g., lts, mediamarkt"
                    className={cn(
                      'w-full px-4 py-3 rounded-lg',
                      'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                  <p className="text-xs text-[var(--sv-gray-500)] mt-1">
                    URL-safe identifier (lowercase, no spaces)
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Organization Name
                  </label>
                  <input
                    type="text"
                    value={data.org.name}
                    onChange={(e) =>
                      setData((prev) => ({
                        ...prev,
                        org: { ...prev.org, name: e.target.value },
                      }))
                    }
                    placeholder="e.g., LTS Transport & Logistik GmbH"
                    className={cn(
                      'w-full px-4 py-3 rounded-lg',
                      'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Tenant Step */}
          {currentStep === 'tenant' && (
            <div>
              <div className="flex items-center gap-3 mb-6">
                <div className="h-12 w-12 rounded-xl bg-blue-500/10 flex items-center justify-center">
                  <Building className="h-6 w-6 text-blue-400" />
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-white">Create Tenant</h2>
                  <p className="text-sm text-[var(--sv-gray-400)]">
                    Tenants are isolated environments within an organization
                  </p>
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Tenant Code
                  </label>
                  <input
                    type="text"
                    value={data.tenant.tenant_code}
                    onChange={(e) =>
                      setData((prev) => ({
                        ...prev,
                        tenant: {
                          ...prev.tenant,
                          tenant_code: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''),
                        },
                      }))
                    }
                    placeholder="e.g., production, staging"
                    className={cn(
                      'w-full px-4 py-3 rounded-lg',
                      'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Tenant Name
                  </label>
                  <input
                    type="text"
                    value={data.tenant.name}
                    onChange={(e) =>
                      setData((prev) => ({
                        ...prev,
                        tenant: { ...prev.tenant, name: e.target.value },
                      }))
                    }
                    placeholder="e.g., Production Environment"
                    className={cn(
                      'w-full px-4 py-3 rounded-lg',
                      'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Site Step */}
          {currentStep === 'site' && (
            <div>
              <div className="flex items-center gap-3 mb-6">
                <div className="h-12 w-12 rounded-xl bg-purple-500/10 flex items-center justify-center">
                  <MapPin className="h-6 w-6 text-purple-400" />
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-white">Create Site</h2>
                  <p className="text-sm text-[var(--sv-gray-400)]">
                    Sites represent physical locations or logical groupings
                  </p>
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Site Code
                  </label>
                  <input
                    type="text"
                    value={data.site.site_code}
                    onChange={(e) =>
                      setData((prev) => ({
                        ...prev,
                        site: {
                          ...prev.site,
                          site_code: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''),
                        },
                      }))
                    }
                    placeholder="e.g., hamburg-hq, munich-depot"
                    className={cn(
                      'w-full px-4 py-3 rounded-lg',
                      'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Site Name
                  </label>
                  <input
                    type="text"
                    value={data.site.name}
                    onChange={(e) =>
                      setData((prev) => ({
                        ...prev,
                        site: { ...prev.site, name: e.target.value },
                      }))
                    }
                    placeholder="e.g., Hamburg Headquarters"
                    className={cn(
                      'w-full px-4 py-3 rounded-lg',
                      'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                      'text-white placeholder-[var(--sv-gray-500)]',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                    Timezone
                  </label>
                  <select
                    value={data.site.timezone}
                    onChange={(e) =>
                      setData((prev) => ({
                        ...prev,
                        site: { ...prev.site, timezone: e.target.value },
                      }))
                    }
                    className={cn(
                      'w-full px-4 py-3 rounded-lg',
                      'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                      'text-white',
                      'focus:outline-none focus:border-[var(--sv-primary)]'
                    )}
                  >
                    <option value="Europe/Berlin">Europe/Berlin</option>
                    <option value="Europe/London">Europe/London</option>
                    <option value="Europe/Paris">Europe/Paris</option>
                    <option value="America/New_York">America/New_York</option>
                    <option value="America/Los_Angeles">America/Los_Angeles</option>
                    <option value="Asia/Tokyo">Asia/Tokyo</option>
                    <option value="UTC">UTC</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* Entitlements Step */}
          {currentStep === 'entitlements' && (
            <div>
              <div className="flex items-center gap-3 mb-6">
                <div className="h-12 w-12 rounded-xl bg-orange-500/10 flex items-center justify-center">
                  <Package className="h-6 w-6 text-orange-400" />
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-white">Enable Packs</h2>
                  <p className="text-sm text-[var(--sv-gray-400)]">
                    Select which packs to enable for this tenant
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                {AVAILABLE_PACKS.map((pack) => {
                  const isSelected = data.entitlements.includes(pack.id);

                  return (
                    <button
                      key={pack.id}
                      onClick={() => toggleEntitlement(pack.id)}
                      className={cn(
                        'w-full flex items-center gap-4 p-4 rounded-lg border text-left transition-colors',
                        isSelected
                          ? 'bg-[var(--sv-primary)]/10 border-[var(--sv-primary)]'
                          : 'bg-[var(--sv-gray-800)] border-[var(--sv-gray-600)] hover:border-[var(--sv-gray-500)]'
                      )}
                    >
                      <div
                        className={cn(
                          'h-6 w-6 rounded-full border-2 flex items-center justify-center',
                          isSelected
                            ? 'bg-[var(--sv-primary)] border-[var(--sv-primary)]'
                            : 'border-[var(--sv-gray-500)]'
                        )}
                      >
                        {isSelected && <CheckCircle className="h-4 w-4 text-white" />}
                      </div>
                      <div>
                        <p className="font-medium text-white">{pack.name}</p>
                        <p className="text-sm text-[var(--sv-gray-400)]">{pack.description}</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Complete Step */}
          {currentStep === 'complete' && (
            <div className="text-center">
              <div className="h-20 w-20 rounded-full bg-green-500/10 flex items-center justify-center mx-auto mb-6">
                <CheckCircle className="h-10 w-10 text-green-400" />
              </div>
              <h2 className="text-2xl font-bold text-white mb-3">Setup Complete!</h2>
              <p className="text-[var(--sv-gray-400)] mb-6 max-w-md mx-auto">
                Your organization <span className="text-white font-medium">{data.org.name}</span>{' '}
                has been created with a tenant, site, and enabled packs.
              </p>
              <div className="bg-[var(--sv-gray-800)] rounded-lg p-4 text-left mb-8">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-[var(--sv-gray-400)]">Organization</p>
                    <p className="text-white font-medium">{data.org.name}</p>
                  </div>
                  <div>
                    <p className="text-[var(--sv-gray-400)]">Tenant</p>
                    <p className="text-white font-medium">{data.tenant.name}</p>
                  </div>
                  <div>
                    <p className="text-[var(--sv-gray-400)]">Site</p>
                    <p className="text-white font-medium">{data.site.name}</p>
                  </div>
                  <div>
                    <p className="text-[var(--sv-gray-400)]">Enabled Packs</p>
                    <p className="text-white font-medium">{data.entitlements.length}</p>
                  </div>
                </div>
              </div>
              <button
                onClick={handleNext}
                className={cn(
                  'inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium',
                  'bg-[var(--sv-primary)] text-white',
                  'hover:bg-[var(--sv-primary-dark)] transition-colors'
                )}
              >
                Go to Organization
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="mt-6 bg-red-500/10 border border-red-500/20 rounded-lg p-4">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {/* Navigation Buttons */}
          {currentStep !== 'welcome' && currentStep !== 'complete' && (
            <div className="flex justify-between mt-8 pt-6 border-t border-[var(--sv-gray-700)]">
              <button
                onClick={handleBack}
                disabled={submitting}
                className={cn(
                  'flex items-center gap-2 px-4 py-2 rounded-lg',
                  'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                  'hover:bg-[var(--sv-gray-700)] transition-colors',
                  'disabled:opacity-50'
                )}
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </button>
              <button
                onClick={handleNext}
                disabled={
                  submitting ||
                  (currentStep === 'organization' && (!data.org.org_code || !data.org.name)) ||
                  (currentStep === 'tenant' &&
                    (!data.tenant.tenant_code || !data.tenant.name)) ||
                  (currentStep === 'site' && (!data.site.site_code || !data.site.name))
                }
                className={cn(
                  'flex items-center gap-2 px-6 py-2 rounded-lg font-medium',
                  'bg-[var(--sv-primary)] text-white',
                  'hover:bg-[var(--sv-primary-dark)] transition-colors',
                  'disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                {submitting ? (
                  'Creating...'
                ) : currentStep === 'entitlements' ? (
                  'Complete Setup'
                ) : (
                  <>
                    Continue
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
