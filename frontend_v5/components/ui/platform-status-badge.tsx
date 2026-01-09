// =============================================================================
// SOLVEREIGN - Platform Status Badge
// =============================================================================
// Badge component for displaying platform entity states:
// - Organization: active/inactive
// - Tenant: active/inactive/blocked
// - Site: active/inactive
//
// This is SEPARATE from PlanStatusBadge which uses UIPlanStatus.
// =============================================================================

'use client';

import { CheckCircle, XCircle, AlertTriangle, Building2, Building, MapPin } from 'lucide-react';
import { cn } from '@/lib/utils';

// =============================================================================
// TYPES
// =============================================================================

export type EntityType = 'org' | 'tenant' | 'site';

export type EntityStatus = 'active' | 'inactive' | 'blocked' | 'degraded';

interface StatusConfig {
  label: string;
  color: string;
  bgColor: string;
  icon: React.ComponentType<{ className?: string }>;
}

// =============================================================================
// STATUS CONFIG
// =============================================================================

const STATUS_CONFIGS: Record<EntityStatus, StatusConfig> = {
  active: {
    label: 'Active',
    color: 'text-green-800 dark:text-green-200',
    bgColor: 'bg-green-100 dark:bg-green-900',
    icon: CheckCircle,
  },
  inactive: {
    label: 'Inactive',
    color: 'text-red-800 dark:text-red-200',
    bgColor: 'bg-red-100 dark:bg-red-900',
    icon: XCircle,
  },
  blocked: {
    label: 'Blocked',
    color: 'text-red-800 dark:text-red-200',
    bgColor: 'bg-red-100 dark:bg-red-900',
    icon: AlertTriangle,
  },
  degraded: {
    label: 'Degraded',
    color: 'text-yellow-800 dark:text-yellow-200',
    bgColor: 'bg-yellow-100 dark:bg-yellow-900',
    icon: AlertTriangle,
  },
};

const ENTITY_ICONS: Record<EntityType, React.ComponentType<{ className?: string }>> = {
  org: Building2,
  tenant: Building,
  site: MapPin,
};

// =============================================================================
// PLATFORM STATUS BADGE
// =============================================================================

interface PlatformStatusBadgeProps {
  status: EntityStatus;
  entityType?: EntityType;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  showLabel?: boolean;
  showEntityIcon?: boolean;
  className?: string;
}

export function PlatformStatusBadge({
  status,
  entityType,
  size = 'md',
  showIcon = true,
  showLabel = true,
  showEntityIcon = false,
  className,
}: PlatformStatusBadgeProps) {
  const config = STATUS_CONFIGS[status];
  const StatusIcon = config.icon;
  const EntityIcon = entityType ? ENTITY_ICONS[entityType] : null;

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
        config.bgColor,
        config.color,
        className
      )}
    >
      {showEntityIcon && EntityIcon && (
        <EntityIcon className={iconSizes[size]} />
      )}
      {showIcon && (
        <StatusIcon className={iconSizes[size]} />
      )}
      {showLabel && <span>{config.label}</span>}
    </span>
  );
}

// =============================================================================
// PLATFORM STATUS DOT
// =============================================================================

interface PlatformStatusDotProps {
  status: EntityStatus;
  size?: 'sm' | 'md' | 'lg';
  showTooltip?: boolean;
  className?: string;
}

export function PlatformStatusDot({
  status,
  size = 'md',
  showTooltip = true,
  className,
}: PlatformStatusDotProps) {
  const sizeClasses = {
    sm: 'h-2 w-2',
    md: 'h-2.5 w-2.5',
    lg: 'h-3 w-3',
  };

  const colorClasses = {
    active: 'bg-green-500',
    inactive: 'bg-red-500',
    blocked: 'bg-red-600',
    degraded: 'bg-yellow-500',
  };

  return (
    <span
      className={cn(
        'inline-block rounded-full',
        sizeClasses[size],
        colorClasses[status],
        className
      )}
      title={showTooltip ? STATUS_CONFIGS[status].label : undefined}
    />
  );
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Convert boolean is_active to EntityStatus
 */
export function toEntityStatus(isActive: boolean): EntityStatus {
  return isActive ? 'active' : 'inactive';
}
