// =============================================================================
// SOLVEREIGN Status Badge Component
// =============================================================================
// Badge component for displaying plan lifecycle status with icons and colors.
// Uses STATUS_CONFIG from tenant-types.ts for consistency.
// =============================================================================

'use client';

import {
  Upload,
  Camera,
  Loader,
  Check,
  XCircle,
  ShieldCheck,
  ShieldX,
  Lock,
  Snowflake,
  Archive,
  Wrench,
  CheckCircle,
  ShieldQuestion,
  LockKeyhole,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { PlanStatus, StatusConfig } from '@/lib/tenant-types';
import { STATUS_CONFIG } from '@/lib/tenant-types';

// Icon mapping for all PlanStatus values
const STATUS_ICONS: Record<PlanStatus, React.ComponentType<{ className?: string }>> = {
  IMPORTED: Upload,
  SNAPSHOTTED: Camera,
  SOLVING: Loader,
  SOLVED: Check,
  FAILED: XCircle,
  AUDIT_PASS: ShieldCheck,
  AUDIT_FAIL: ShieldX,
  LOCKED: Lock,
  FROZEN: Snowflake,
  REPAIRING: Wrench,
  REPAIRED: CheckCircle,
  RE_AUDIT: ShieldQuestion,
  RE_LOCKED: LockKeyhole,
  SUPERSEDED: Archive,
};

// =============================================================================
// STATUS BADGE
// =============================================================================

interface StatusBadgeProps {
  status: PlanStatus;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  showLabel?: boolean;
  className?: string;
}

export function StatusBadge({
  status,
  size = 'md',
  showIcon = true,
  showLabel = true,
  className,
}: StatusBadgeProps) {
  const config = STATUS_CONFIG[status];
  const Icon = STATUS_ICONS[status];

  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs gap-1',
    md: 'px-2 py-1 text-xs gap-1.5',
    lg: 'px-3 py-1.5 text-sm gap-2',
  };

  const iconSizes = {
    sm: 'h-3 w-3',
    md: 'h-3.5 w-3.5',
    lg: 'h-4 w-4',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center font-medium rounded-full',
        sizeClasses[size],
        config.pulse && 'status-solving',
        className
      )}
      style={{
        backgroundColor: config.bgColor,
        color: config.color,
      }}
    >
      {showIcon && Icon && (
        <Icon
          className={cn(
            iconSizes[size],
            config.pulse && 'animate-spin'
          )}
        />
      )}
      {showLabel && <span>{config.label}</span>}
    </span>
  );
}

// =============================================================================
// STATUS DOT (Compact Version)
// =============================================================================

interface StatusDotProps {
  status: PlanStatus;
  size?: 'sm' | 'md' | 'lg';
  showTooltip?: boolean;
  className?: string;
}

export function StatusDot({
  status,
  size = 'md',
  showTooltip = true,
  className,
}: StatusDotProps) {
  const config = STATUS_CONFIG[status];

  const sizeClasses = {
    sm: 'h-2 w-2',
    md: 'h-2.5 w-2.5',
    lg: 'h-3 w-3',
  };

  return (
    <span
      className={cn(
        'inline-block rounded-full',
        sizeClasses[size],
        config.pulse && 'animate-pulse',
        className
      )}
      style={{ backgroundColor: config.color }}
      title={showTooltip ? config.label : undefined}
    />
  );
}

// =============================================================================
// STATUS ICON (Icon Only)
// =============================================================================

interface StatusIconProps {
  status: PlanStatus;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function StatusIcon({ status, size = 'md', className }: StatusIconProps) {
  const config = STATUS_CONFIG[status];
  const Icon = STATUS_ICONS[status];

  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-5 w-5',
    lg: 'h-6 w-6',
  };

  if (!Icon) return null;

  return (
    <span style={{ color: config.color }}>
      <Icon
        className={cn(
          sizeClasses[size],
          config.pulse && 'animate-spin',
          className
        )}
      />
    </span>
  );
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

export function getStatusConfig(status: PlanStatus): StatusConfig {
  return STATUS_CONFIG[status];
}

export function getStatusLabel(status: PlanStatus): string {
  return STATUS_CONFIG[status].label;
}

export function getStatusActions(status: PlanStatus) {
  return STATUS_CONFIG[status].actions;
}
