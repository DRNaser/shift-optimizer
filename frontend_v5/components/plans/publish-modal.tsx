// =============================================================================
// SOLVEREIGN - Publish Modal with Freeze Window Handling (V3.7.2)
// =============================================================================
// Modal for publishing plans with freeze window detection and force override.
// Implements the Wien Pilot Gate requirements:
// - Freeze status display with countdown
// - Force publish for Approver/Admin only
// - Minimum 10-char force reason
// - Proper error handling for 409/422/403
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import { X, AlertTriangle, Lock, Clock, ShieldAlert, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth, useApi, AppRoles, type FreezeStatusResponse } from '@/lib/auth';
import { cn } from '@/lib/utils';

// =============================================================================
// TYPES
// =============================================================================

interface PublishModalProps {
  isOpen: boolean;
  onClose: () => void;
  planId: string;
  planName?: string;
  onPublishSuccess?: (snapshotId: string) => void;
}

interface PublishError {
  code: string;
  message: string;
  freezeUntil?: string;
  minutesRemaining?: number;
}

// =============================================================================
// COMPONENT
// =============================================================================

export function PublishModal({
  isOpen,
  onClose,
  planId,
  planName,
  onPublishSuccess,
}: PublishModalProps) {
  // Auth state
  const { user, hasRole, hasAnyRole } = useAuth();
  const { api } = useApi();

  // Local state
  const [freezeStatus, setFreezeStatus] = useState<FreezeStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCheckingFreeze, setIsCheckingFreeze] = useState(true);
  const [error, setError] = useState<PublishError | null>(null);

  // Form state
  const [reason, setReason] = useState('');
  const [forcePublish, setForcePublish] = useState(false);
  const [forceReason, setForceReason] = useState('');

  // Computed
  const canForcePublish = hasAnyRole([
    AppRoles.APPROVER,
    AppRoles.TENANT_ADMIN,
    AppRoles.PLATFORM_ADMIN,
  ]);
  const isFrozen = freezeStatus?.is_frozen ?? false;
  const forceReasonValid = forceReason.length >= 10;
  const canSubmit = reason.length > 0 && (!isFrozen || !forcePublish || forceReasonValid);

  // =============================================================================
  // EFFECTS
  // =============================================================================

  // Check freeze status when modal opens
  useEffect(() => {
    if (isOpen && planId) {
      checkFreezeStatus();
    }
  }, [isOpen, planId]);

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setReason('');
      setForcePublish(false);
      setForceReason('');
      setError(null);
    }
  }, [isOpen]);

  // =============================================================================
  // HANDLERS
  // =============================================================================

  const checkFreezeStatus = useCallback(async () => {
    setIsCheckingFreeze(true);
    try {
      const response = await api.plans.getFreezeStatus(planId);
      if (response.data) {
        setFreezeStatus(response.data);
      }
    } catch (err) {
      console.error('Failed to check freeze status:', err);
    } finally {
      setIsCheckingFreeze(false);
    }
  }, [api, planId]);

  const handlePublish = async () => {
    if (!canSubmit) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await api.plans.publish(planId, {
        reason,
        force_during_freeze: isFrozen && forcePublish,
        force_reason: isFrozen && forcePublish ? forceReason : undefined,
      });

      if (response.error) {
        // Handle specific error codes
        const err = response.error;

        if (err.code === 'FREEZE_WINDOW_ACTIVE') {
          setError({
            code: 'FREEZE_WINDOW_ACTIVE',
            message: err.message,
            freezeUntil: err.details?.freeze_until as string,
            minutesRemaining: err.details?.minutes_remaining as number,
          });
          // Refresh freeze status
          await checkFreezeStatus();
        } else if (err.code === 'FORBIDDEN' || response.status === 403) {
          setError({
            code: 'FORBIDDEN',
            message: err.details?.error === 'APP_TOKEN_NOT_ALLOWED'
              ? 'Service accounts cannot publish plans. Please use a personal account.'
              : 'You do not have permission to publish this plan.',
          });
        } else if (err.code === 'VALIDATION_ERROR' || response.status === 422) {
          setError({
            code: 'VALIDATION_ERROR',
            message: err.message,
          });
        } else {
          setError({
            code: err.code,
            message: err.message,
          });
        }
        return;
      }

      // Success
      if (response.data && onPublishSuccess) {
        onPublishSuccess(response.data.snapshot_id);
      }
      onClose();
    } catch (err) {
      setError({
        code: 'UNKNOWN_ERROR',
        message: err instanceof Error ? err.message : 'An unexpected error occurred',
      });
    } finally {
      setIsLoading(false);
    }
  };

  // =============================================================================
  // RENDER
  // =============================================================================

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Publish Plan
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X className="h-5 w-5 text-gray-500" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Plan Info */}
          {planName && (
            <div className="text-sm text-gray-600 dark:text-gray-400">
              Publishing: <span className="font-medium">{planName}</span>
            </div>
          )}

          {/* Loading freeze check */}
          {isCheckingFreeze && (
            <div className="flex items-center gap-2 text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm">Checking freeze status...</span>
            </div>
          )}

          {/* Freeze Warning */}
          {!isCheckingFreeze && isFrozen && (
            <FreezeWarning
              freezeUntil={freezeStatus?.freeze_until}
              minutesRemaining={freezeStatus?.minutes_remaining}
              canForce={canForcePublish}
            />
          )}

          {/* Error Display */}
          {error && <ErrorDisplay error={error} />}

          {/* Reason Input */}
          <div>
            <label
              htmlFor="publish-reason"
              className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
            >
              Publish Reason <span className="text-red-500">*</span>
            </label>
            <textarea
              id="publish-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g., Weekly schedule ready for dispatchers"
              className={cn(
                'w-full px-3 py-2 border rounded-lg',
                'focus:outline-none focus:ring-2 focus:ring-blue-500',
                'dark:bg-gray-800 dark:border-gray-600'
              )}
              rows={2}
            />
          </div>

          {/* Force Publish Section (only if frozen AND user can force) */}
          {!isCheckingFreeze && isFrozen && canForcePublish && (
            <ForcePublishSection
              forcePublish={forcePublish}
              setForcePublish={setForcePublish}
              forceReason={forceReason}
              setForceReason={setForceReason}
              forceReasonValid={forceReasonValid}
            />
          )}

          {/* Non-Approver Blocked Message */}
          {!isCheckingFreeze && isFrozen && !canForcePublish && (
            <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
              <div className="flex gap-2">
                <ShieldAlert className="h-5 w-5 text-red-500 flex-shrink-0" />
                <div className="text-sm text-red-700 dark:text-red-300">
                  <strong>Cannot publish during freeze window.</strong>
                  <p className="mt-1">
                    Only users with Approver, Tenant Admin, or Platform Admin role
                    can force publish during a freeze.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-200 dark:border-gray-700">
          <Button variant="outline" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            onClick={handlePublish}
            disabled={!canSubmit || isLoading || isCheckingFreeze || (isFrozen && !canForcePublish)}
          >
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Publishing...
              </>
            ) : isFrozen && forcePublish ? (
              <>
                <ShieldAlert className="h-4 w-4" />
                Force Publish
              </>
            ) : (
              <>
                <Lock className="h-4 w-4" />
                Publish
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// SUB-COMPONENTS
// =============================================================================

interface FreezeWarningProps {
  freezeUntil?: string;
  minutesRemaining?: number;
  canForce: boolean;
}

function FreezeWarning({ freezeUntil, minutesRemaining, canForce }: FreezeWarningProps) {
  const formatTime = (isoString?: string) => {
    if (!isoString) return 'Unknown';
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

  const formatRemaining = (minutes?: number) => {
    if (!minutes) return '';
    if (minutes < 60) return `${minutes} Min`;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  };

  return (
    <div className="p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
      <div className="flex gap-2">
        <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0" />
        <div className="flex-1">
          <div className="font-medium text-amber-800 dark:text-amber-200">
            Freeze Window Active
          </div>
          <div className="text-sm text-amber-700 dark:text-amber-300 mt-1 space-y-1">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4" />
              <span>Until: {formatTime(freezeUntil)}</span>
              {minutesRemaining && (
                <span className="px-2 py-0.5 bg-amber-200 dark:bg-amber-800 rounded text-xs font-medium">
                  {formatRemaining(minutesRemaining)} remaining
                </span>
              )}
            </div>
            {canForce ? (
              <p className="mt-2">
                You can force publish with a valid reason (minimum 10 characters).
              </p>
            ) : (
              <p className="mt-2">
                Normal publish is blocked. Contact an Approver if urgent.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

interface ForcePublishSectionProps {
  forcePublish: boolean;
  setForcePublish: (value: boolean) => void;
  forceReason: string;
  setForceReason: (value: string) => void;
  forceReasonValid: boolean;
}

function ForcePublishSection({
  forcePublish,
  setForcePublish,
  forceReason,
  setForceReason,
  forceReasonValid,
}: ForcePublishSectionProps) {
  return (
    <div className="space-y-3 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={forcePublish}
          onChange={(e) => setForcePublish(e.target.checked)}
          className="w-4 h-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
        />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          Force publish during freeze window
        </span>
      </label>

      {forcePublish && (
        <div>
          <label
            htmlFor="force-reason"
            className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
          >
            Force Reason <span className="text-red-500">*</span>
            <span className="text-gray-500 font-normal ml-1">
              (min. 10 characters)
            </span>
          </label>
          <textarea
            id="force-reason"
            value={forceReason}
            onChange={(e) => setForceReason(e.target.value)}
            placeholder="e.g., CRITICAL: Driver sick call requires immediate re-schedule"
            className={cn(
              'w-full px-3 py-2 border rounded-lg',
              'focus:outline-none focus:ring-2',
              forceReasonValid
                ? 'border-green-300 focus:ring-green-500'
                : 'border-gray-300 focus:ring-amber-500',
              'dark:bg-gray-800 dark:border-gray-600'
            )}
            rows={2}
          />
          <div className="flex justify-between mt-1">
            <span
              className={cn(
                'text-xs',
                forceReasonValid ? 'text-green-600' : 'text-gray-500'
              )}
            >
              {forceReason.length}/10 characters
            </span>
            {forceReasonValid && (
              <span className="text-xs text-green-600">Valid reason</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface ErrorDisplayProps {
  error: PublishError;
}

function ErrorDisplay({ error }: ErrorDisplayProps) {
  const getErrorStyle = () => {
    switch (error.code) {
      case 'FREEZE_WINDOW_ACTIVE':
        return 'bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-200';
      case 'FORBIDDEN':
        return 'bg-red-50 border-red-200 text-red-800 dark:bg-red-900/20 dark:border-red-800 dark:text-red-200';
      case 'VALIDATION_ERROR':
        return 'bg-orange-50 border-orange-200 text-orange-800 dark:bg-orange-900/20 dark:border-orange-800 dark:text-orange-200';
      default:
        return 'bg-red-50 border-red-200 text-red-800 dark:bg-red-900/20 dark:border-red-800 dark:text-red-200';
    }
  };

  return (
    <div className={cn('p-3 border rounded-lg', getErrorStyle())}>
      <div className="flex gap-2">
        <AlertTriangle className="h-5 w-5 flex-shrink-0" />
        <div className="text-sm">
          <div className="font-medium">{getErrorTitle(error.code)}</div>
          <div className="mt-1">{error.message}</div>
        </div>
      </div>
    </div>
  );
}

function getErrorTitle(code: string): string {
  switch (code) {
    case 'FREEZE_WINDOW_ACTIVE':
      return 'Freeze Window Active (HTTP 409)';
    case 'FORBIDDEN':
      return 'Access Denied (HTTP 403)';
    case 'VALIDATION_ERROR':
      return 'Validation Error (HTTP 422)';
    default:
      return 'Error';
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export default PublishModal;
