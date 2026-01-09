// =============================================================================
// SOLVEREIGN - Plan Status Badge (Uses UIPlanStatus)
// =============================================================================
// Badge component for displaying DERIVED plan status.
// Uses UIPlanStatus from plan-status-ui.ts, NOT raw PlanStatus.
//
// For org/tenant active/inactive states, use PlatformStatusBadge instead.
// =============================================================================

'use client';

import {
  Upload,
  Loader,
  Check,
  XCircle,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  Lock,
  Snowflake,
  Archive,
  Clock,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { UIPlanStatus } from '@/lib/plan-status-ui';
import { UI_STATUS_CONFIG, getStatusColor } from '@/lib/plan-status-ui';

// Icon mapping for UI status
const STATUS_ICONS: Record<UIPlanStatus, React.ComponentType<{ className?: string }>> = {
  QUEUED: Clock,
  SOLVING: Loader,
  SOLVED: Check,
  AUDIT_PASS: ShieldCheck,
  AUDIT_FAIL: XCircle,
  AUDIT_WARN: ShieldAlert,
  DRAFT: Upload,
  LOCKED: Lock,
  FROZEN: Snowflake,
  FAILED: AlertTriangle,
  SUPERSEDED: Archive,
};

// =============================================================================
// PLAN STATUS BADGE
// =============================================================================

interface PlanStatusBadgeProps {
  status: UIPlanStatus;
  badges?: string[];
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  showLabel?: boolean;
  className?: string;
}

export function PlanStatusBadge({
  status,
  badges = [],
  size = 'md',
  showIcon = true,
  showLabel = true,
  className,
}: PlanStatusBadgeProps) {
  const config = UI_STATUS_CONFIG[status];
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
    <div className="flex items-center gap-1.5 flex-wrap">
      <span
        className={cn(
          'inline-flex items-center font-medium rounded-full',
          sizeClasses[size],
          getStatusColor(status),
          config.pulse && 'animate-pulse',
          className
        )}
      >
        {showIcon && Icon && (
          <Icon
            className={cn(
              iconSizes[size],
              status === 'SOLVING' && 'animate-spin'
            )}
          />
        )}
        {showLabel && <span>{config.label}</span>}
      </span>
      {badges.map((badge, idx) => (
        <span
          key={idx}
          className={cn(
            'inline-flex items-center font-medium rounded-full',
            sizeClasses[size],
            'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200'
          )}
        >
          <Snowflake className={iconSizes[size]} />
          <span className="ml-1">{badge}</span>
        </span>
      ))}
    </div>
  );
}

// =============================================================================
// PLAN STATUS DOT (Compact)
// =============================================================================

interface PlanStatusDotProps {
  status: UIPlanStatus;
  size?: 'sm' | 'md' | 'lg';
  showTooltip?: boolean;
  className?: string;
}

export function PlanStatusDot({
  status,
  size = 'md',
  showTooltip = true,
  className,
}: PlanStatusDotProps) {
  const config = UI_STATUS_CONFIG[status];

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
// PLAN STATUS ICON
// =============================================================================

interface PlanStatusIconProps {
  status: UIPlanStatus;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function PlanStatusIcon({ status, size = 'md', className }: PlanStatusIconProps) {
  const config = UI_STATUS_CONFIG[status];
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
          status === 'SOLVING' && 'animate-spin',
          className
        )}
      />
    </span>
  );
}
