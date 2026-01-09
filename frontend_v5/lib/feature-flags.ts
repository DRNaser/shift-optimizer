// =============================================================================
// SOLVEREIGN - Feature Flags Configuration
// =============================================================================
// Centralized feature flag management for gradual rollout.
//
// Environment Variables:
//   NEXT_PUBLIC_FF_DISPATCHER_COCKPIT - Enable dispatcher cockpit UI (default: false)
//   NEXT_PUBLIC_FF_DISPATCHER_COCKPIT_ROLES - Allowed roles (comma-separated)
//
// Usage:
//   import { isFeatureEnabled, canAccessFeature } from '@/lib/feature-flags';
//   if (isFeatureEnabled('dispatcherCockpit')) { ... }
//   if (canAccessFeature('dispatcherCockpit', userRole)) { ... }
// =============================================================================

// =============================================================================
// TYPES
// =============================================================================

export type FeatureFlag =
  | 'dispatcherCockpit'
  | 'multiSiteOnboarding'
  | 'advancedAudits'
  | 'evidenceDownload';

export type PlatformRole =
  | 'platform_admin'
  | 'platform_ops'
  | 'dispatcher'
  | 'ops_lead'
  | 'auditor'
  | 'platform_viewer';

interface FeatureFlagConfig {
  enabled: boolean;
  allowedRoles: PlatformRole[];
  description: string;
}

// =============================================================================
// FEATURE FLAG DEFINITIONS
// =============================================================================

const FEATURE_FLAGS: Record<FeatureFlag, FeatureFlagConfig> = {
  dispatcherCockpit: {
    // Default OFF in production, ON for internal users
    enabled: process.env.NEXT_PUBLIC_FF_DISPATCHER_COCKPIT === 'true',
    allowedRoles: parseRoles(
      process.env.NEXT_PUBLIC_FF_DISPATCHER_COCKPIT_ROLES ||
      'platform_admin,platform_ops,dispatcher,ops_lead'
    ),
    description: 'Dispatcher cockpit UI for runs list, detail, publish/lock actions',
  },
  multiSiteOnboarding: {
    enabled: process.env.NEXT_PUBLIC_FF_MULTI_SITE_ONBOARDING === 'true',
    allowedRoles: ['platform_admin', 'platform_ops'],
    description: 'Multi-site onboarding wizard (Graz, etc.)',
  },
  advancedAudits: {
    enabled: process.env.NEXT_PUBLIC_FF_ADVANCED_AUDITS === 'true',
    allowedRoles: ['platform_admin', 'auditor'],
    description: 'Advanced audit analytics and drill-down',
  },
  evidenceDownload: {
    enabled: process.env.NEXT_PUBLIC_FF_EVIDENCE_DOWNLOAD !== 'false', // Default ON
    allowedRoles: ['platform_admin', 'platform_ops', 'dispatcher', 'ops_lead', 'auditor'],
    description: 'Evidence pack download functionality',
  },
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function parseRoles(rolesStr: string): PlatformRole[] {
  return rolesStr
    .split(',')
    .map((r) => r.trim() as PlatformRole)
    .filter(Boolean);
}

// =============================================================================
// PUBLIC API
// =============================================================================

/**
 * Check if a feature flag is enabled globally
 */
export function isFeatureEnabled(flag: FeatureFlag): boolean {
  const config = FEATURE_FLAGS[flag];
  return config?.enabled ?? false;
}

/**
 * Check if a user with a specific role can access a feature
 * Requires both: feature enabled AND role allowed
 */
export function canAccessFeature(flag: FeatureFlag, userRole: string): boolean {
  const config = FEATURE_FLAGS[flag];
  if (!config) return false;
  if (!config.enabled) return false;
  return config.allowedRoles.includes(userRole as PlatformRole);
}

/**
 * Get the feature flag configuration (for debugging)
 */
export function getFeatureFlagConfig(flag: FeatureFlag): FeatureFlagConfig | null {
  return FEATURE_FLAGS[flag] ?? null;
}

/**
 * Get all enabled feature flags
 */
export function getEnabledFeatures(): FeatureFlag[] {
  return (Object.keys(FEATURE_FLAGS) as FeatureFlag[]).filter((flag) =>
    FEATURE_FLAGS[flag].enabled
  );
}

/**
 * Get features accessible by a role
 */
export function getAccessibleFeatures(userRole: string): FeatureFlag[] {
  return (Object.keys(FEATURE_FLAGS) as FeatureFlag[]).filter((flag) =>
    canAccessFeature(flag, userRole)
  );
}

// =============================================================================
// ROLE PERMISSION HELPERS
// =============================================================================

/**
 * Check if a role can perform publish operations
 */
export function canPublish(userRole: string): boolean {
  const publishRoles: PlatformRole[] = ['platform_admin', 'platform_ops', 'dispatcher', 'ops_lead'];
  return publishRoles.includes(userRole as PlatformRole);
}

/**
 * Check if a role can perform lock operations
 */
export function canLock(userRole: string): boolean {
  const lockRoles: PlatformRole[] = ['platform_admin', 'platform_ops', 'dispatcher', 'ops_lead'];
  return lockRoles.includes(userRole as PlatformRole);
}

/**
 * Check if a role can submit repair requests
 */
export function canRequestRepair(userRole: string): boolean {
  const repairRoles: PlatformRole[] = ['platform_admin', 'platform_ops', 'dispatcher', 'ops_lead'];
  return repairRoles.includes(userRole as PlatformRole);
}

/**
 * Check if a role is viewer-only (read-only access)
 */
export function isViewerOnly(userRole: string): boolean {
  const viewerRoles: PlatformRole[] = ['platform_viewer', 'auditor'];
  return viewerRoles.includes(userRole as PlatformRole);
}

// =============================================================================
// SITE ENABLEMENT (Wien-only gate)
// =============================================================================

const ENABLED_SITES = (process.env.NEXT_PUBLIC_ENABLED_SITES || 'wien').split(',').map(s => s.trim());

/**
 * Check if a site is enabled for publish/lock operations
 */
export function isSiteEnabled(siteCode: string): boolean {
  return ENABLED_SITES.includes(siteCode.toLowerCase());
}

/**
 * Get list of enabled sites
 */
export function getEnabledSites(): string[] {
  return [...ENABLED_SITES];
}
