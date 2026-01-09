// =============================================================================
// SOLVEREIGN - Legacy Snapshot Warning (V3.7.2)
// =============================================================================
// Warning components for legacy snapshots created before V3.7.2 that have
// empty assignments_snapshot and routes_snapshot payloads.
//
// These snapshots:
// - KPIs and audit hashes are still valid
// - Assignment details are NOT available for reconstruction
// - Cannot be replayed/reconstructed
// =============================================================================

'use client';

import { AlertTriangle, Archive, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { PlanSnapshot } from '@/lib/auth';

// =============================================================================
// LEGACY BADGE
// =============================================================================

interface LegacyBadgeProps {
  className?: string;
}

/**
 * Compact badge for marking legacy snapshots in lists and tables.
 */
export function LegacyBadge({ className }: LegacyBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded',
        'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
        className
      )}
      title="Legacy snapshot from before V3.7.2 - assignment details not available"
    >
      <Archive className="h-3 w-3" />
      LEGACY
    </span>
  );
}

// =============================================================================
// LEGACY SNAPSHOT ALERT
// =============================================================================

interface LegacySnapshotAlertProps {
  variant?: 'warning' | 'info';
  className?: string;
}

/**
 * Alert banner for legacy snapshot detail views.
 * Use in snapshot detail pages and publish history.
 */
export function LegacySnapshotAlert({
  variant = 'warning',
  className,
}: LegacySnapshotAlertProps) {
  const isWarning = variant === 'warning';

  return (
    <div
      className={cn(
        'p-4 rounded-lg border',
        isWarning
          ? 'bg-amber-50 border-amber-200 dark:bg-amber-900/20 dark:border-amber-800'
          : 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800',
        className
      )}
    >
      <div className="flex gap-3">
        {isWarning ? (
          <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
        ) : (
          <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
        )}
        <div className="flex-1">
          <h4
            className={cn(
              'font-medium',
              isWarning
                ? 'text-amber-800 dark:text-amber-200'
                : 'text-blue-800 dark:text-blue-200'
            )}
          >
            Legacy Snapshot (Pre-V3.7.2)
          </h4>
          <div
            className={cn(
              'mt-1 text-sm',
              isWarning
                ? 'text-amber-700 dark:text-amber-300'
                : 'text-blue-700 dark:text-blue-300'
            )}
          >
            <p>
              This snapshot was created before V3.7.2 when payload capture was implemented.
            </p>
            <ul className="mt-2 space-y-1 list-disc list-inside">
              <li>Assignment details are not available for reconstruction</li>
              <li>KPIs and audit hashes remain valid for compliance</li>
              <li>This snapshot cannot be replayed or reconstructed</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// SNAPSHOT STATUS INDICATOR
// =============================================================================

interface SnapshotStatusProps {
  snapshot: PlanSnapshot;
  showLegacyBadge?: boolean;
  className?: string;
}

/**
 * Combined status indicator for snapshots.
 * Shows frozen status and legacy badge when applicable.
 */
export function SnapshotStatus({
  snapshot,
  showLegacyBadge = true,
  className,
}: SnapshotStatusProps) {
  return (
    <div className={cn('flex items-center gap-2 flex-wrap', className)}>
      {/* Status Badge */}
      <StatusBadge status={snapshot.snapshot_status} />

      {/* Frozen Badge */}
      {snapshot.is_frozen && <FrozenBadge />}

      {/* Legacy Badge */}
      {showLegacyBadge && snapshot.is_legacy && <LegacyBadge />}
    </div>
  );
}

// =============================================================================
// HELPER COMPONENTS
// =============================================================================

interface StatusBadgeProps {
  status: 'ACTIVE' | 'SUPERSEDED' | 'ARCHIVED';
}

function StatusBadge({ status }: StatusBadgeProps) {
  const config = {
    ACTIVE: {
      bg: 'bg-green-100 dark:bg-green-900/30',
      text: 'text-green-800 dark:text-green-300',
      label: 'Active',
    },
    SUPERSEDED: {
      bg: 'bg-gray-100 dark:bg-gray-800',
      text: 'text-gray-700 dark:text-gray-400',
      label: 'Superseded',
    },
    ARCHIVED: {
      bg: 'bg-purple-100 dark:bg-purple-900/30',
      text: 'text-purple-800 dark:text-purple-300',
      label: 'Archived',
    },
  };

  const { bg, text, label } = config[status];

  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 text-xs font-medium rounded',
        bg,
        text
      )}
    >
      {label}
    </span>
  );
}

function FrozenBadge() {
  return (
    <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-300">
      Frozen
    </span>
  );
}

// =============================================================================
// SNAPSHOT HISTORY ITEM
// =============================================================================

interface SnapshotHistoryItemProps {
  snapshot: PlanSnapshot;
  isSelected?: boolean;
  onClick?: () => void;
  className?: string;
}

/**
 * List item for snapshot history with legacy warning.
 */
export function SnapshotHistoryItem({
  snapshot,
  isSelected,
  onClick,
  className,
}: SnapshotHistoryItemProps) {
  const formatDate = (isoString: string) => {
    try {
      return new Date(isoString).toLocaleString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div
      className={cn(
        'p-3 rounded-lg border cursor-pointer transition-colors',
        isSelected
          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
          : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600',
        snapshot.is_legacy && !isSelected && 'border-l-4 border-l-amber-400',
        className
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900 dark:text-gray-100">
              Version {snapshot.version_number}
            </span>
            <SnapshotStatus snapshot={snapshot} />
          </div>
          <div className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {formatDate(snapshot.published_at)} by {snapshot.published_by}
          </div>
        </div>

        {/* KPIs Preview */}
        {snapshot.kpis && (
          <div className="text-right text-sm text-gray-600 dark:text-gray-400">
            <div>{snapshot.kpis.vehicles_used} vehicles</div>
            <div>{snapshot.kpis.total_distance_km?.toFixed(1)} km</div>
          </div>
        )}
      </div>

      {/* Legacy Warning in List */}
      {snapshot.is_legacy && (
        <div className="mt-2 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
          <AlertTriangle className="h-3 w-3" />
          <span>Not replayable - pre-V3.7.2 snapshot</span>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// UTILITY: Check if snapshot is legacy
// =============================================================================

/**
 * Check if a snapshot is legacy (missing payload data).
 * Use this when the is_legacy flag is not available from backend.
 */
export function isLegacySnapshot(snapshot: {
  assignments_snapshot?: unknown;
  routes_snapshot?: unknown;
}): boolean {
  return (
    !snapshot.assignments_snapshot ||
    (Array.isArray(snapshot.assignments_snapshot) && snapshot.assignments_snapshot.length === 0)
  );
}

// =============================================================================
// EXPORTS
// =============================================================================

export default {
  LegacyBadge,
  LegacySnapshotAlert,
  SnapshotStatus,
  SnapshotHistoryItem,
  isLegacySnapshot,
};
