// =============================================================================
// SOLVEREIGN - Run Status Badge
// =============================================================================
// Badge component for displaying solver run audit status:
// - PASS: All 7 audits passed, ready for publish
// - WARN: Some warnings but publishable with approval
// - FAIL: Audit failures, cannot publish
// - BLOCKED: Kill switch active or gates failed
// - PENDING: Run in progress or not yet audited
// =============================================================================

'use client';

import {
  CheckCircle,
  AlertTriangle,
  XCircle,
  Ban,
  Clock,
  Shield,
  ShieldOff,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// =============================================================================
// TYPES
// =============================================================================

export type RunStatus = 'PASS' | 'WARN' | 'FAIL' | 'BLOCKED' | 'PENDING';

export type RunPublishState = 'draft' | 'published' | 'locked';

interface StatusConfig {
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ComponentType<{ className?: string }>;
}

// =============================================================================
// STATUS CONFIG
// =============================================================================

const STATUS_CONFIGS: Record<RunStatus, StatusConfig> = {
  PASS: {
    label: 'Pass',
    color: 'text-green-400',
    bgColor: 'bg-green-500/10',
    borderColor: 'border-green-500/30',
    icon: CheckCircle,
  },
  WARN: {
    label: 'Warn',
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/10',
    borderColor: 'border-yellow-500/30',
    icon: AlertTriangle,
  },
  FAIL: {
    label: 'Fail',
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
    icon: XCircle,
  },
  BLOCKED: {
    label: 'Blocked',
    color: 'text-red-400',
    bgColor: 'bg-red-500/20',
    borderColor: 'border-red-500/40',
    icon: Ban,
  },
  PENDING: {
    label: 'Pending',
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10',
    borderColor: 'border-gray-500/30',
    icon: Clock,
  },
};

const PUBLISH_STATE_CONFIGS: Record<RunPublishState, StatusConfig> = {
  draft: {
    label: 'Draft',
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10',
    borderColor: 'border-gray-500/30',
    icon: Clock,
  },
  published: {
    label: 'Published',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30',
    icon: Shield,
  },
  locked: {
    label: 'Locked',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500/30',
    icon: ShieldOff,
  },
};

// =============================================================================
// RUN STATUS BADGE
// =============================================================================

interface RunStatusBadgeProps {
  status: RunStatus;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  showLabel?: boolean;
  className?: string;
}

export function RunStatusBadge({
  status,
  size = 'md',
  showIcon = true,
  showLabel = true,
  className,
}: RunStatusBadgeProps) {
  const config = STATUS_CONFIGS[status];
  const StatusIcon = config.icon;

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
        'inline-flex items-center font-medium rounded border',
        sizeClasses[size],
        config.bgColor,
        config.color,
        config.borderColor,
        className
      )}
    >
      {showIcon && <StatusIcon className={iconSizes[size]} />}
      {showLabel && <span>{config.label}</span>}
    </span>
  );
}

// =============================================================================
// PUBLISH STATE BADGE
// =============================================================================

interface PublishStateBadgeProps {
  state: RunPublishState;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  showLabel?: boolean;
  className?: string;
}

export function PublishStateBadge({
  state,
  size = 'md',
  showIcon = true,
  showLabel = true,
  className,
}: PublishStateBadgeProps) {
  const config = PUBLISH_STATE_CONFIGS[state];
  const StateIcon = config.icon;

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
        'inline-flex items-center font-medium rounded border',
        sizeClasses[size],
        config.bgColor,
        config.color,
        config.borderColor,
        className
      )}
    >
      {showIcon && <StateIcon className={iconSizes[size]} />}
      {showLabel && <span>{config.label}</span>}
    </span>
  );
}

// =============================================================================
// KILL SWITCH BADGE
// =============================================================================

interface KillSwitchBadgeProps {
  active: boolean;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function KillSwitchBadge({
  active,
  size = 'md',
  className,
}: KillSwitchBadgeProps) {
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

  if (active) {
    return (
      <span
        className={cn(
          'inline-flex items-center font-medium rounded border',
          sizeClasses[size],
          'bg-red-500/20 text-red-400 border-red-500/40',
          'animate-pulse',
          className
        )}
      >
        <Ban className={iconSizes[size]} />
        <span>KILL SWITCH ACTIVE</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        'inline-flex items-center font-medium rounded border',
        sizeClasses[size],
        'bg-green-500/10 text-green-400 border-green-500/30',
        className
      )}
    >
      <CheckCircle className={iconSizes[size]} />
      <span>System OK</span>
    </span>
  );
}

// =============================================================================
// AUDIT CHECK BADGE
// =============================================================================

interface AuditCheckBadgeProps {
  passed: number;
  total: number;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function AuditCheckBadge({
  passed,
  total,
  size = 'md',
  className,
}: AuditCheckBadgeProps) {
  const allPassed = passed === total;
  const nonePass = passed === 0;

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

  const color = allPassed
    ? 'bg-green-500/10 text-green-400 border-green-500/30'
    : nonePass
    ? 'bg-red-500/10 text-red-400 border-red-500/30'
    : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30';

  const Icon = allPassed ? CheckCircle : nonePass ? XCircle : AlertTriangle;

  return (
    <span
      className={cn(
        'inline-flex items-center font-medium rounded border',
        sizeClasses[size],
        color,
        className
      )}
    >
      <Icon className={iconSizes[size]} />
      <span>
        {passed}/{total} Audits
      </span>
    </span>
  );
}
