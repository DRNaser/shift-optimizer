// =============================================================================
// SOLVEREIGN Tenant Status Banner
// =============================================================================
// Persistent banner showing tenant/site operational status.
//
// STATES:
//   - healthy: No banner shown (normal operation)
//   - degraded: Yellow warning banner (writes still allowed)
//   - blocked: Red error banner (writes disabled)
//
// REQUIREMENTS (Phase 2):
//   - If blocked => disable all write operations, show reason_code
//   - Link to /tenant/status for details
//   - Auto-refresh status every 30 seconds
// =============================================================================

'use client';

import { useState, useEffect } from 'react';
import { AlertTriangle, XCircle, RefreshCw, ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';
import Link from 'next/link';

export interface TenantStatusData {
  overall_status: 'healthy' | 'degraded' | 'blocked';
  is_write_blocked: boolean;
  reason_code: string | null;
  reason_message: string | null;
  escalation_id: string | null;
  blocked_since: string | null;
}

interface StatusBannerProps {
  status: TenantStatusData | null;
  isLoading: boolean;
  onRefresh: () => void;
  className?: string;
}

export function TenantStatusBanner({
  status,
  isLoading,
  onRefresh,
  className,
}: StatusBannerProps) {
  // Don't show banner for healthy status
  if (!status || status.overall_status === 'healthy') {
    return null;
  }

  const isBlocked = status.overall_status === 'blocked';
  const isDegraded = status.overall_status === 'degraded';

  return (
    <div
      className={cn(
        'relative px-4 py-3 flex items-center gap-3',
        isBlocked && 'bg-[var(--sv-error)] text-white',
        isDegraded && 'bg-[var(--sv-warning)] text-[var(--sv-gray-900)]',
        className
      )}
      role="alert"
      aria-live="polite"
    >
      {/* Icon */}
      <div className="flex-shrink-0">
        {isBlocked ? (
          <XCircle className="h-5 w-5" />
        ) : (
          <AlertTriangle className="h-5 w-5" />
        )}
      </div>

      {/* Message */}
      <div className="flex-1 min-w-0">
        <span className="font-semibold">
          {isBlocked ? 'Betrieb blockiert' : 'Eingeschraenkter Betrieb'}
        </span>
        {status.reason_code && (
          <span className="mx-2">|</span>
        )}
        {status.reason_code && (
          <code
            className={cn(
              'px-1.5 py-0.5 rounded text-xs font-mono',
              isBlocked ? 'bg-white/20' : 'bg-black/10'
            )}
          >
            {status.reason_code}
          </code>
        )}
        {status.reason_message && (
          <span className="ml-2 text-sm opacity-90">
            {status.reason_message}
          </span>
        )}
        {isBlocked && (
          <span className="ml-2 text-sm font-medium">
            - Schreiboperationen deaktiviert
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {/* Refresh Button */}
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className={cn(
            'p-1.5 rounded-md transition-colors',
            isBlocked
              ? 'hover:bg-white/20 disabled:opacity-50'
              : 'hover:bg-black/10 disabled:opacity-50'
          )}
          title="Status aktualisieren"
        >
          <RefreshCw
            className={cn('h-4 w-4', isLoading && 'animate-spin')}
          />
        </button>

        {/* Link to Status Page */}
        <Link
          href="/tenant/status"
          className={cn(
            'flex items-center gap-1 px-2 py-1 rounded-md text-sm font-medium transition-colors',
            isBlocked
              ? 'bg-white/20 hover:bg-white/30'
              : 'bg-black/10 hover:bg-black/20'
          )}
        >
          Details
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}

// =============================================================================
// STATUS CONTEXT (for blocking write operations)
// =============================================================================

import { createContext, useContext, useCallback, type ReactNode } from 'react';

interface TenantStatusContextValue {
  status: TenantStatusData | null;
  isLoading: boolean;
  isWriteBlocked: boolean;
  refresh: () => Promise<void>;
  getBlockReason: () => string | null;
}

const TenantStatusContext = createContext<TenantStatusContextValue | null>(null);

interface TenantStatusProviderProps {
  children: ReactNode;
  tenantCode: string;
  siteCode: string;
}

export function TenantStatusProvider({
  children,
  tenantCode,
  siteCode,
}: TenantStatusProviderProps) {
  const [status, setStatus] = useState<TenantStatusData | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`/api/tenant/status?tenant=${tenantCode}&site=${siteCode}`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (err) {
      console.error('[TenantStatus] Failed to fetch status:', err);
    } finally {
      setIsLoading(false);
    }
  }, [tenantCode, siteCode]);

  // Initial fetch
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(fetchStatus, 30_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const refresh = useCallback(async () => {
    await fetchStatus();
  }, [fetchStatus]);

  const getBlockReason = useCallback(() => {
    if (!status || !status.is_write_blocked) return null;
    return status.reason_code || 'UNKNOWN_BLOCK';
  }, [status]);

  return (
    <TenantStatusContext.Provider
      value={{
        status,
        isLoading,
        isWriteBlocked: status?.is_write_blocked || false,
        refresh,
        getBlockReason,
      }}
    >
      {children}
    </TenantStatusContext.Provider>
  );
}

export function useTenantStatus(): TenantStatusContextValue {
  const context = useContext(TenantStatusContext);
  if (!context) {
    throw new Error('useTenantStatus must be used within a TenantStatusProvider');
  }
  return context;
}

// =============================================================================
// WRITE GUARD COMPONENT
// =============================================================================
// Wraps write actions and disables them if tenant is blocked.
// Shows tooltip/reason when user attempts blocked action.
// =============================================================================

interface WriteGuardProps {
  children: ReactNode;
  fallback?: ReactNode;
  showReason?: boolean;
}

export function WriteGuard({
  children,
  fallback = null,
  showReason = false,
}: WriteGuardProps) {
  const { isWriteBlocked, getBlockReason } = useTenantStatus();

  if (isWriteBlocked) {
    if (showReason) {
      return (
        <div className="relative group">
          <div className="opacity-50 pointer-events-none">
            {children}
          </div>
          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-[var(--sv-error)] text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            Blockiert: {getBlockReason()}
          </div>
        </div>
      );
    }
    return <>{fallback}</>;
  }

  return <>{children}</>;
}

// =============================================================================
// BLOCKED BUTTON WRAPPER
// =============================================================================
// Wraps a button and disables it if writes are blocked.
// Shows blocking reason on hover.
// =============================================================================

interface BlockedButtonProps {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  type?: 'button' | 'submit';
}

export function BlockedButton({
  children,
  onClick,
  disabled = false,
  className,
  type = 'button',
}: BlockedButtonProps) {
  const { isWriteBlocked, getBlockReason } = useTenantStatus();
  const isDisabled = disabled || isWriteBlocked;

  return (
    <div className="relative group inline-block">
      <button
        type={type}
        onClick={onClick}
        disabled={isDisabled}
        className={cn(
          className,
          isWriteBlocked && 'cursor-not-allowed'
        )}
      >
        {children}
      </button>
      {isWriteBlocked && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-[var(--sv-error)] text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-50">
          Blockiert: {getBlockReason()}
        </div>
      )}
    </div>
  );
}
