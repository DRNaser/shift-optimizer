// =============================================================================
// SOLVEREIGN - Plan Status UI Derivation Layer
// =============================================================================
// IMPORTANT: PlanStatus (raw backend type) vs UIPlanStatus (derived for UI)
//
// This module is the SINGLE SOURCE OF TRUTH for UI status derivation.
// StatusBadge and all UI components should use UIPlanStatus, not PlanStatus.
//
// The backend returns raw status fields. The UI derives display status from:
// - plan.status (base status)
// - auditResult (AUDIT_FAIL if any check fails)
// - freezeState (adds FROZEN badge if freeze_status != 'NONE')
// =============================================================================

import type { RoutingPlan, AuditResult } from './tenant-api';

// =============================================================================
// UI STATUS TYPES
// =============================================================================

/**
 * UI-friendly status for display in the frontend.
 * Derived from backend fields, NOT stored as a separate backend field.
 */
export type UIPlanStatus =
  | 'QUEUED'       // Waiting to solve
  | 'SOLVING'      // Currently solving
  | 'SOLVED'       // Solver finished
  | 'AUDIT_PASS'   // All audits passed
  | 'AUDIT_FAIL'   // At least one audit failed
  | 'AUDIT_WARN'   // All passed but some warnings
  | 'DRAFT'        // Ready for lock
  | 'LOCKED'       // Immutable
  | 'FROZEN'       // Has frozen stops
  | 'FAILED'       // Solver failed
  | 'SUPERSEDED';  // Replaced by newer plan

/**
 * Audit summary for UI derivation.
 */
export interface AuditSummary {
  all_passed: boolean;
  checks_run: number;
  checks_passed: number;
  checks_warn: number;
  checks_fail: number;
  results: AuditResult[];
}

/**
 * Freeze state for UI derivation.
 */
export interface FreezeState {
  plan_id: string;
  total_stops: number;
  frozen_stops: number;
  unfrozen_stops: number;
  freeze_status: 'NONE' | 'PARTIAL' | 'FULL';
  frozen_stop_ids: string[];
}

// =============================================================================
// STATUS DERIVATION
// =============================================================================

/**
 * Derive UI-friendly status from backend fields.
 *
 * Priority order:
 * 1. FAILED, SUPERSEDED (terminal states)
 * 2. LOCKED (with optional FROZEN badge)
 * 3. AUDIT_FAIL (blocks lock)
 * 4. AUDIT_PASS / AUDIT_WARN (ready for lock)
 * 5. SOLVING, QUEUED (in progress)
 */
export function deriveUIStatus(
  plan: RoutingPlan,
  auditSummary?: AuditSummary | null,
  freezeState?: FreezeState | null
): { status: UIPlanStatus; badges: string[] } {
  const badges: string[] = [];

  // Terminal states
  if (plan.status === 'FAILED') {
    return { status: 'FAILED', badges };
  }
  if (plan.status === 'SUPERSEDED') {
    return { status: 'SUPERSEDED', badges };
  }

  // Add FROZEN badge if applicable
  if (freezeState && freezeState.freeze_status !== 'NONE') {
    badges.push(`FROZEN (${freezeState.frozen_stops}/${freezeState.total_stops})`);
  }

  // LOCKED state
  if (plan.status === 'LOCKED') {
    return { status: 'LOCKED', badges };
  }

  // Check audit results if available
  if (auditSummary) {
    if (auditSummary.checks_fail > 0) {
      return { status: 'AUDIT_FAIL', badges };
    }
    if (auditSummary.checks_warn > 0 && auditSummary.all_passed) {
      return { status: 'AUDIT_WARN', badges };
    }
    if (auditSummary.all_passed) {
      return { status: 'AUDIT_PASS', badges };
    }
  }

  // Plan status direct mapping
  if (plan.status === 'AUDITED' || plan.status === 'DRAFT') {
    return { status: 'DRAFT', badges };
  }
  if (plan.status === 'SOLVED') {
    return { status: 'SOLVED', badges };
  }
  if (plan.status === 'SOLVING') {
    return { status: 'SOLVING', badges };
  }
  if (plan.status === 'QUEUED') {
    return { status: 'QUEUED', badges };
  }

  // Default (shouldn't happen, but type-safe)
  return { status: 'DRAFT', badges };
}

// =============================================================================
// STATUS DISPLAY CONFIG
// =============================================================================

export interface UIStatusConfig {
  color: string;
  bgColor: string;
  label: string;
  labelShort: string;
  pulse?: boolean;
}

/**
 * Get display configuration for a UI status.
 */
export const UI_STATUS_CONFIG: Record<UIPlanStatus, UIStatusConfig> = {
  QUEUED: {
    color: 'var(--sv-gray-600)',
    bgColor: 'var(--sv-gray-100)',
    label: 'Warteschlange',
    labelShort: 'QUEUE',
  },
  SOLVING: {
    color: 'var(--sv-info)',
    bgColor: 'var(--sv-info-light)',
    label: 'Berechnung läuft',
    labelShort: 'CALC',
    pulse: true,
  },
  SOLVED: {
    color: 'var(--sv-warning)',
    bgColor: 'var(--sv-warning-light)',
    label: 'Berechnet',
    labelShort: 'DONE',
  },
  AUDIT_PASS: {
    color: 'var(--sv-success)',
    bgColor: 'var(--sv-success-light)',
    label: 'Audit OK',
    labelShort: 'PASS',
  },
  AUDIT_FAIL: {
    color: 'var(--sv-error)',
    bgColor: 'var(--sv-error-light)',
    label: 'Audit FAIL',
    labelShort: 'FAIL',
  },
  AUDIT_WARN: {
    color: 'var(--sv-warning)',
    bgColor: 'var(--sv-warning-light)',
    label: 'Audit WARN',
    labelShort: 'WARN',
  },
  DRAFT: {
    color: 'var(--sv-info)',
    bgColor: 'var(--sv-info-light)',
    label: 'Entwurf',
    labelShort: 'DRAFT',
  },
  LOCKED: {
    color: 'var(--sv-success)',
    bgColor: 'var(--sv-success-light)',
    label: 'Gesperrt',
    labelShort: 'LOCK',
  },
  FROZEN: {
    color: '#0891B2', // cyan-600
    bgColor: '#CFFAFE', // cyan-100
    label: 'Eingefroren',
    labelShort: 'FRZ',
  },
  FAILED: {
    color: 'var(--sv-error)',
    bgColor: 'var(--sv-error-light)',
    label: 'Fehlgeschlagen',
    labelShort: 'ERR',
  },
  SUPERSEDED: {
    color: 'var(--sv-gray-500)',
    bgColor: 'var(--sv-gray-100)',
    label: 'Ersetzt',
    labelShort: 'OLD',
  },
};

/**
 * Get CSS class for status badge (Tailwind).
 */
export function getStatusColor(status: UIPlanStatus): string {
  switch (status) {
    case 'LOCKED':
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
    case 'AUDIT_PASS':
    case 'DRAFT':
      return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200';
    case 'AUDIT_WARN':
      return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
    case 'AUDIT_FAIL':
    case 'FAILED':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
    case 'SOLVING':
    case 'QUEUED':
      return 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200';
    case 'SUPERSEDED':
      return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
    case 'FROZEN':
      return 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200';
    case 'SOLVED':
      return 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

/**
 * Get human-readable label for status.
 */
export function getStatusLabel(status: UIPlanStatus): string {
  return UI_STATUS_CONFIG[status]?.label ?? status;
}
