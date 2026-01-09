// =============================================================================
// SOLVEREIGN Tenant & Site Types
// =============================================================================
// Multi-tenant SaaS architecture types for Enterprise platform.
//
// SECURITY NOTES:
// - All tenant/site context comes from server via /api/tenant/me
// - current_site_id is server-authoritative (session-based)
// - Guards in frontend are UX-only; backend enforces all checks
// =============================================================================

// =============================================================================
// TENANT TYPES
// =============================================================================

export interface Tenant {
  id: string;
  slug: string;           // URL-friendly: "lts-transport"
  name: string;           // Display: "LTS Transport u. Logistik GmbH"
  domain?: string;        // Custom domain if enabled
  logo_url?: string;
  primary_color?: string; // White-labeling
  created_at: string;
  settings: TenantSettings;
}

export interface TenantSettings {
  timezone: string;                    // "Europe/Berlin"
  locale: string;                      // "de-DE"
  week_start_day: 0 | 1;               // 0=Sunday, 1=Monday
  default_freeze_hours: number;        // Default 12
  enabled_packs: PackId[];
  features: TenantFeatures;
}

export interface TenantFeatures {
  multi_site: boolean;
  custom_domain: boolean;
  sso_enabled: boolean;
  api_access: boolean;
  evidence_retention_days: number;
}

// =============================================================================
// SITE TYPES
// =============================================================================

export interface Site {
  id: string;
  tenant_id: string;
  code: string;           // "HH-NORD", "MUC-WEST"
  name: string;           // "Hamburg Nord"
  address?: SiteAddress;
  timezone: string;       // Can override tenant
  is_active: boolean;
  created_at: string;
  settings: SiteSettings;
}

export interface SiteAddress {
  street: string;
  city: string;
  postal_code: string;
  country: string;
  lat?: number;
  lng?: number;
}

export interface SiteSettings {
  default_depot_id?: string;
  shift_start_time: string;    // "06:00"
  shift_end_time: string;      // "22:00"
  max_drivers_per_shift: number;
}

// =============================================================================
// PACK TYPES (Domain Packs)
// =============================================================================
// NOTE: 'core' is ALWAYS enabled - contains Audits/Lock/Freeze/Evidence/Repair
// Optional packs add domain-specific features on top of Core
// =============================================================================

export type PackId = 'core' | 'routing' | 'forecasting' | 'compliance';

export interface Pack {
  id: PackId;
  name: string;
  description: string;
  icon: string;           // Lucide icon name
  is_enabled: boolean;
  entitlements: string[];
  version: string;
}

// Core is ALWAYS enabled - contains critical platform features
export const PACK_REGISTRY: Record<PackId, Omit<Pack, 'is_enabled'>> = {
  // CORE: Always enabled, NOT optional
  core: {
    id: 'core',
    name: 'SOLVEREIGN Core',
    description: 'Shift scheduling, audits, lock/freeze, evidence, repair framework',
    icon: 'Calendar',
    entitlements: [
      'scenarios',
      'plans',
      'audits',        // Core audit framework
      'evidence',      // Evidence pack generation
      'lock',          // Plan locking
      'freeze',        // Freeze windows
      'repair',        // Repair framework
    ],
    version: '3.3',
  },
  // OPTIONAL: Routing domain pack
  routing: {
    id: 'routing',
    name: 'Routing Pack',
    description: 'Vehicle routing and tour optimization',
    icon: 'MapPin',
    entitlements: ['routing-scenarios', 'routes', 'depots', 'routing-audits'],
    version: '1.0',
  },
  // OPTIONAL: Forecasting domain pack
  forecasting: {
    id: 'forecasting',
    name: 'Forecasting Pack',
    description: 'Demand forecasting and capacity planning',
    icon: 'TrendingUp',
    entitlements: ['forecasts', 'predictions', 'capacity'],
    version: '0.9',
  },
  // OPTIONAL: Extended compliance dashboard (NOT the audit framework itself)
  compliance: {
    id: 'compliance',
    name: 'Compliance Dashboard',
    description: 'Extended compliance reporting and labor law analytics',
    icon: 'Shield',
    entitlements: ['compliance-dashboard', 'labor-law-reports', 'custom-audit-rules'],
    version: '1.0',
  },
};

// =============================================================================
// USER & ROLE TYPES
// =============================================================================

export type UserRole = 'VIEWER' | 'PLANNER' | 'APPROVER' | 'ADMIN' | 'PLATFORM_ADMIN';

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url?: string;
  tenant_id: string;
  role: UserRole;
  site_ids: string[];     // Sites user can access (empty = all)
  permissions: Permission[];
  last_login_at?: string;
}

export type Permission =
  | 'scenario:read'
  | 'scenario:write'
  | 'plan:read'
  | 'plan:write'
  | 'plan:lock'
  | 'plan:repair'
  | 'audit:read'
  | 'evidence:read'
  | 'evidence:export'
  | 'tenant:manage'
  | 'user:manage'
  | 'site:manage';

export const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  VIEWER: ['scenario:read', 'plan:read', 'audit:read', 'evidence:read'],
  PLANNER: [
    'scenario:read', 'scenario:write',
    'plan:read', 'plan:write',
    'audit:read',
    'evidence:read', 'evidence:export',
  ],
  APPROVER: [
    'scenario:read', 'scenario:write',
    'plan:read', 'plan:write', 'plan:lock', 'plan:repair',
    'audit:read',
    'evidence:read', 'evidence:export',
  ],
  ADMIN: [
    'scenario:read', 'scenario:write',
    'plan:read', 'plan:write', 'plan:lock', 'plan:repair',
    'audit:read',
    'evidence:read', 'evidence:export',
    'user:manage', 'site:manage',
  ],
  PLATFORM_ADMIN: [
    'scenario:read', 'scenario:write',
    'plan:read', 'plan:write', 'plan:lock', 'plan:repair',
    'audit:read',
    'evidence:read', 'evidence:export',
    'tenant:manage', 'user:manage', 'site:manage',
  ],
};

// =============================================================================
// PLAN LIFECYCLE STATE MACHINE (EXTENDED)
// =============================================================================
// Full lifecycle:
//   IMPORTED → SNAPSHOTTED → SOLVING → SOLVED → AUDIT_PASS/AUDIT_FAIL
//   AUDIT_PASS → LOCKED → FROZEN
//   LOCKED → REPAIRING → REPAIRED → RE_AUDIT → RE_LOCK
//   Any → SUPERSEDED (when new version created)
//   SOLVING → FAILED (on error)
//
// LOCKED ≠ FROZEN:
//   LOCKED = Plan approved, can still be repaired
//   FROZEN = Within freeze window, no changes allowed (DB-enforced)
// =============================================================================

export type PlanStatus =
  | 'IMPORTED'       // Raw forecast imported
  | 'SNAPSHOTTED'    // Teams/vehicles snapshotted
  | 'SOLVING'        // Solver running
  | 'SOLVED'         // Solver complete, pending audit
  | 'FAILED'         // Solver failed
  | 'AUDIT_PASS'     // All audits passed
  | 'AUDIT_FAIL'     // One or more audits failed (can't lock)
  | 'LOCKED'         // Released for operations
  | 'FROZEN'         // Within freeze window (DB-enforced immutability)
  | 'REPAIRING'      // Repair in progress
  | 'REPAIRED'       // Repair complete, pending re-audit
  | 'RE_AUDIT'       // Re-audit after repair
  | 'RE_LOCKED'      // Re-locked after repair
  | 'SUPERSEDED';    // Replaced by newer version

export interface StatusConfig {
  color: string;
  bgColor: string;
  icon: string;
  label: string;
  labelShort: string;
  description: string;
  actions: StatusAction[];
  pulse?: boolean;
  canEdit: boolean;
  canLock: boolean;
}

export type StatusAction =
  | 'snapshot'
  | 'solve'
  | 'retry'
  | 'view-error'
  | 'run-audit'
  | 'edit'
  | 're-solve'
  | 'lock'
  | 'evidence'
  | 'repair'
  | 'view-violations'
  | 're-audit'
  | 're-lock';

// Valid state transitions
export const STATUS_TRANSITIONS: Record<PlanStatus, PlanStatus[]> = {
  IMPORTED: ['SNAPSHOTTED'],
  SNAPSHOTTED: ['SOLVING'],
  SOLVING: ['SOLVED', 'FAILED'],
  SOLVED: ['AUDIT_PASS', 'AUDIT_FAIL'],
  FAILED: ['SOLVING', 'SUPERSEDED'],
  AUDIT_PASS: ['LOCKED'],
  AUDIT_FAIL: ['SOLVING', 'SUPERSEDED'],  // Must re-solve, can't lock
  LOCKED: ['FROZEN', 'REPAIRING', 'SUPERSEDED'],
  FROZEN: ['SUPERSEDED'],  // No actions during freeze
  REPAIRING: ['REPAIRED', 'FAILED'],
  REPAIRED: ['RE_AUDIT'],
  RE_AUDIT: ['RE_LOCKED', 'AUDIT_FAIL'],
  RE_LOCKED: ['FROZEN', 'REPAIRING', 'SUPERSEDED'],
  SUPERSEDED: [],  // Terminal state
};

export const STATUS_CONFIG: Record<PlanStatus, StatusConfig> = {
  IMPORTED: {
    color: 'var(--sv-status-imported)',
    bgColor: 'var(--sv-gray-100)',
    icon: 'Upload',
    label: 'Importiert',
    labelShort: 'IMP',
    description: 'Forecast importiert, bereit für Snapshot',
    actions: ['snapshot'],
    canEdit: true,
    canLock: false,
  },
  SNAPSHOTTED: {
    color: 'var(--sv-status-snapshotted)',
    bgColor: 'var(--sv-info-light)',
    icon: 'Camera',
    label: 'Snapshot erstellt',
    labelShort: 'SNAP',
    description: 'Teams/Fahrzeuge eingefroren, bereit für Solver',
    actions: ['solve'],
    canEdit: true,
    canLock: false,
  },
  SOLVING: {
    color: 'var(--sv-status-solving)',
    bgColor: 'var(--sv-info-light)',
    icon: 'Loader',
    label: 'Berechnung läuft',
    labelShort: 'CALC',
    description: 'Solver optimiert Schichtplan',
    actions: [],
    pulse: true,
    canEdit: false,
    canLock: false,
  },
  SOLVED: {
    color: 'var(--sv-status-solved)',
    bgColor: 'var(--sv-warning-light)',
    icon: 'Check',
    label: 'Berechnet',
    labelShort: 'DONE',
    description: 'Optimierung abgeschlossen, Audit ausstehend',
    actions: ['run-audit'],
    canEdit: true,
    canLock: false,
  },
  FAILED: {
    color: 'var(--sv-status-failed)',
    bgColor: 'var(--sv-error-light)',
    icon: 'XCircle',
    label: 'Fehlgeschlagen',
    labelShort: 'FAIL',
    description: 'Solver-Fehler aufgetreten',
    actions: ['retry', 'view-error'],
    canEdit: true,
    canLock: false,
  },
  AUDIT_PASS: {
    color: 'var(--sv-status-audited)',
    bgColor: 'var(--sv-success-light)',
    icon: 'ShieldCheck',
    label: 'Audit bestanden',
    labelShort: 'PASS',
    description: 'Alle Compliance-Checks bestanden',
    actions: ['lock', 'evidence'],
    canEdit: true,
    canLock: true,
  },
  AUDIT_FAIL: {
    color: 'var(--sv-error)',
    bgColor: 'var(--sv-error-light)',
    icon: 'ShieldX',
    label: 'Audit fehlgeschlagen',
    labelShort: 'AFAIL',
    description: 'Compliance-Verstöße gefunden, Freigabe blockiert',
    actions: ['view-violations', 're-solve'],
    canEdit: true,
    canLock: false,  // CRITICAL: Cannot lock if audit fails
  },
  LOCKED: {
    color: 'var(--sv-status-locked)',
    bgColor: 'var(--sv-success-light)',
    icon: 'Lock',
    label: 'Freigegeben',
    labelShort: 'LOCK',
    description: 'Plan freigegeben für Betrieb',
    actions: ['evidence', 'repair'],
    canEdit: false,
    canLock: false,
  },
  FROZEN: {
    color: 'var(--sv-status-frozen)',
    bgColor: '#CFFAFE',
    icon: 'Snowflake',
    label: 'Eingefroren',
    labelShort: 'FRZ',
    description: 'Innerhalb Freeze-Fenster, keine Änderungen möglich',
    actions: ['evidence'],
    canEdit: false,
    canLock: false,
  },
  REPAIRING: {
    color: 'var(--sv-info)',
    bgColor: 'var(--sv-info-light)',
    icon: 'Wrench',
    label: 'Reparatur läuft',
    labelShort: 'REP',
    description: 'Repair-Engine bearbeitet Änderungen',
    actions: [],
    pulse: true,
    canEdit: false,
    canLock: false,
  },
  REPAIRED: {
    color: 'var(--sv-warning)',
    bgColor: 'var(--sv-warning-light)',
    icon: 'CheckCircle',
    label: 'Repariert',
    labelShort: 'REPD',
    description: 'Reparatur abgeschlossen, Re-Audit erforderlich',
    actions: ['re-audit'],
    canEdit: false,
    canLock: false,
  },
  RE_AUDIT: {
    color: 'var(--sv-warning)',
    bgColor: 'var(--sv-warning-light)',
    icon: 'ShieldQuestion',
    label: 'Re-Audit läuft',
    labelShort: 'RAUD',
    description: 'Erneute Compliance-Prüfung',
    actions: [],
    pulse: true,
    canEdit: false,
    canLock: false,
  },
  RE_LOCKED: {
    color: 'var(--sv-status-locked)',
    bgColor: 'var(--sv-success-light)',
    icon: 'LockKeyhole',
    label: 'Erneut freigegeben',
    labelShort: 'RLCK',
    description: 'Nach Reparatur erneut freigegeben',
    actions: ['evidence', 'repair'],
    canEdit: false,
    canLock: false,
  },
  SUPERSEDED: {
    color: 'var(--sv-status-superseded)',
    bgColor: 'var(--sv-gray-100)',
    icon: 'Archive',
    label: 'Ersetzt',
    labelShort: 'OLD',
    description: 'Durch neuere Version ersetzt',
    actions: [],
    canEdit: false,
    canLock: false,
  },
};

// =============================================================================
// TENANT CONTEXT STATE
// =============================================================================

export interface TenantContextState {
  tenant: Tenant | null;
  sites: Site[];
  currentSite: Site | null;
  user: User | null;
  enabledPacks: Pack[];
  isLoading: boolean;
  isSwitchingSite?: boolean;
  error: Error | null;
}

export interface TenantContextActions {
  switchSite: (siteId: string) => Promise<boolean>;  // Returns success
  refreshTenant: () => Promise<void>;
  hasPermission: (permission: Permission) => boolean;
  hasPackAccess: (packId: PackId) => boolean;
}

export type TenantContext = TenantContextState & TenantContextActions;

// =============================================================================
// API REQUEST/RESPONSE TYPES
// =============================================================================

export interface TenantMeResponse {
  tenant: Tenant;
  sites: Site[];
  user: User;
  enabled_packs: PackId[];
  current_site_id: string | null;  // Server-authoritative current site
}

export interface SwitchSiteRequest {
  site_id: string;
}

export interface SwitchSiteResponse {
  success: boolean;
  current_site_id: string;
}

// ETag for optimistic concurrency
export interface ETaggedResource<T> {
  data: T;
  etag: string;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

export function canTransitionTo(from: PlanStatus, to: PlanStatus): boolean {
  return STATUS_TRANSITIONS[from]?.includes(to) ?? false;
}

export function getAvailableActions(status: PlanStatus): StatusAction[] {
  return STATUS_CONFIG[status]?.actions ?? [];
}

export function canLockPlan(status: PlanStatus): boolean {
  return STATUS_CONFIG[status]?.canLock ?? false;
}
