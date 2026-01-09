// =============================================================================
// SOLVEREIGN Tenant Error Handler
// =============================================================================
// Global error handling for tenant-scoped operations.
//
// ERROR MAPPING:
//   401 => Session expired / Not logged in => Login UI
//   403 => Permission denied => Permissions UI
//   409 => Conflict (idempotency, concurrent edit) => Conflict UI
//   503 => Service unavailable (escalation) => Escalation link
//
// USAGE:
//   Wrap tenant pages with TenantErrorBoundary.
//   Use useTenantError() hook for programmatic error handling.
// =============================================================================

'use client';

import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { AlertTriangle, Lock, RefreshCw, LogIn, ShieldX, AlertCircle, Wrench } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

// =============================================================================
// ERROR TYPES
// =============================================================================

export interface TenantError {
  code: string;
  status: number;
  message: string;
  details?: Record<string, unknown>;
  timestamp: string;
}

export type ErrorType = '401' | '403' | '409' | '503' | 'NETWORK' | 'UNKNOWN';

function classifyError(status: number, code?: string): ErrorType {
  if (status === 401) return '401';
  if (status === 403) return '403';
  if (status === 409) return '409';
  if (status === 503) return '503';
  if (code === 'NETWORK_ERROR') return 'NETWORK';
  return 'UNKNOWN';
}

// =============================================================================
// ERROR CONTEXT
// =============================================================================

interface TenantErrorContextValue {
  error: TenantError | null;
  errorType: ErrorType | null;
  setError: (error: TenantError | null) => void;
  clearError: () => void;
  handleApiError: (status: number, code: string, message: string, details?: Record<string, unknown>) => void;
}

const TenantErrorContext = createContext<TenantErrorContextValue | null>(null);

interface TenantErrorProviderProps {
  children: ReactNode;
}

export function TenantErrorProvider({ children }: TenantErrorProviderProps) {
  const [error, setErrorState] = useState<TenantError | null>(null);
  const [errorType, setErrorType] = useState<ErrorType | null>(null);

  const setError = useCallback((err: TenantError | null) => {
    setErrorState(err);
    setErrorType(err ? classifyError(err.status, err.code) : null);
  }, []);

  const clearError = useCallback(() => {
    setErrorState(null);
    setErrorType(null);
  }, []);

  const handleApiError = useCallback((
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>
  ) => {
    const err: TenantError = {
      code,
      status,
      message,
      details,
      timestamp: new Date().toISOString(),
    };
    setError(err);
  }, [setError]);

  return (
    <TenantErrorContext.Provider
      value={{
        error,
        errorType,
        setError,
        clearError,
        handleApiError,
      }}
    >
      {children}
    </TenantErrorContext.Provider>
  );
}

export function useTenantError(): TenantErrorContextValue {
  const context = useContext(TenantErrorContext);
  if (!context) {
    throw new Error('useTenantError must be used within a TenantErrorProvider');
  }
  return context;
}

// =============================================================================
// ERROR DISPLAY COMPONENT
// =============================================================================

interface ErrorDisplayProps {
  error: TenantError;
  errorType: ErrorType;
  onDismiss?: () => void;
  onRetry?: () => void;
}

export function ErrorDisplay({
  error,
  errorType,
  onDismiss,
  onRetry,
}: ErrorDisplayProps) {
  const configs: Record<ErrorType, {
    icon: typeof AlertTriangle;
    title: string;
    bgColor: string;
    textColor: string;
    action?: { label: string; href?: string; onClick?: () => void };
  }> = {
    '401': {
      icon: LogIn,
      title: 'Sitzung abgelaufen',
      bgColor: 'bg-[var(--sv-warning-light)]',
      textColor: 'text-[var(--sv-warning)]',
      action: { label: 'Erneut anmelden', href: '/login' },
    },
    '403': {
      icon: ShieldX,
      title: 'Keine Berechtigung',
      bgColor: 'bg-[var(--sv-error-light)]',
      textColor: 'text-[var(--sv-error)]',
    },
    '409': {
      icon: AlertCircle,
      title: 'Konflikt',
      bgColor: 'bg-[var(--sv-warning-light)]',
      textColor: 'text-[var(--sv-warning)]',
      action: onRetry ? { label: 'Erneut versuchen', onClick: onRetry } : undefined,
    },
    '503': {
      icon: Wrench,
      title: 'Service nicht verfuegbar',
      bgColor: 'bg-[var(--sv-error-light)]',
      textColor: 'text-[var(--sv-error)]',
      action: { label: 'Status pruefen', href: '/tenant/status' },
    },
    'NETWORK': {
      icon: RefreshCw,
      title: 'Netzwerkfehler',
      bgColor: 'bg-[var(--sv-gray-100)]',
      textColor: 'text-[var(--sv-gray-600)]',
      action: onRetry ? { label: 'Erneut versuchen', onClick: onRetry } : undefined,
    },
    'UNKNOWN': {
      icon: AlertTriangle,
      title: 'Unbekannter Fehler',
      bgColor: 'bg-[var(--sv-error-light)]',
      textColor: 'text-[var(--sv-error)]',
    },
  };

  const config = configs[errorType];
  const Icon = config.icon;

  return (
    <div className={cn('rounded-lg p-4', config.bgColor)}>
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className={cn('flex-shrink-0 p-2 rounded-full', config.bgColor)}>
          <Icon className={cn('h-5 w-5', config.textColor)} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <h3 className={cn('font-semibold', config.textColor)}>
            {config.title}
          </h3>
          <p className="mt-1 text-sm text-[var(--foreground)]">
            {error.message}
          </p>
          {error.code && (
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              Fehlercode: <code className="bg-black/5 px-1 rounded">{error.code}</code>
            </p>
          )}

          {/* Actions */}
          <div className="mt-3 flex items-center gap-2">
            {config.action && (
              config.action.href ? (
                <Link
                  href={config.action.href}
                  className={cn(
                    'px-3 py-1.5 rounded-md text-sm font-medium',
                    'bg-[var(--sv-primary)] text-white hover:bg-[var(--sv-primary-dark)]'
                  )}
                >
                  {config.action.label}
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={config.action.onClick}
                  className={cn(
                    'px-3 py-1.5 rounded-md text-sm font-medium',
                    'bg-[var(--sv-primary)] text-white hover:bg-[var(--sv-primary-dark)]'
                  )}
                >
                  {config.action.label}
                </button>
              )
            )}
            {onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="px-3 py-1.5 rounded-md text-sm font-medium text-[var(--muted-foreground)] hover:bg-black/5"
              >
                Schliessen
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// ERROR MODAL
// =============================================================================
// Full-screen modal for critical errors (401, 503)
// =============================================================================

interface ErrorModalProps {
  error: TenantError;
  errorType: ErrorType;
  onClose?: () => void;
}

export function ErrorModal({ error, errorType, onClose }: ErrorModalProps) {
  // Only show modal for critical errors
  const isCritical = errorType === '401' || errorType === '503';

  if (!isCritical) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
        <ErrorDisplay
          error={error}
          errorType={errorType}
          onDismiss={errorType !== '401' ? onClose : undefined}
        />
      </div>
    </div>
  );
}

// =============================================================================
// ERROR TOAST
// =============================================================================
// Dismissible toast for non-critical errors (403, 409)
// =============================================================================

interface ErrorToastProps {
  error: TenantError;
  errorType: ErrorType;
  onDismiss: () => void;
  onRetry?: () => void;
  duration?: number;
}

export function ErrorToast({
  error,
  errorType,
  onDismiss,
  onRetry,
  duration = 5000,
}: ErrorToastProps) {
  // Auto-dismiss after duration
  useState(() => {
    if (duration > 0) {
      const timer = setTimeout(onDismiss, duration);
      return () => clearTimeout(timer);
    }
  });

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-md animate-in slide-in-from-bottom-5">
      <ErrorDisplay
        error={error}
        errorType={errorType}
        onDismiss={onDismiss}
        onRetry={onRetry}
      />
    </div>
  );
}

// =============================================================================
// GLOBAL ERROR HANDLER COMPONENT
// =============================================================================
// Renders appropriate error UI based on error type
// =============================================================================

interface GlobalErrorHandlerProps {
  onRetry?: () => void;
}

export function GlobalErrorHandler({ onRetry }: GlobalErrorHandlerProps) {
  const { error, errorType, clearError } = useTenantError();

  if (!error || !errorType) return null;

  // Critical errors show modal
  if (errorType === '401' || errorType === '503') {
    return (
      <ErrorModal
        error={error}
        errorType={errorType}
        onClose={clearError}
      />
    );
  }

  // Other errors show toast
  return (
    <ErrorToast
      error={error}
      errorType={errorType}
      onDismiss={clearError}
      onRetry={onRetry}
    />
  );
}

// =============================================================================
// API RESPONSE HANDLER UTILITY
// =============================================================================
// Helper function to process API responses and trigger error handling
// =============================================================================

export function createApiHandler(handleApiError: TenantErrorContextValue['handleApiError']) {
  return async function handleResponse<T>(
    response: { data?: T; error?: { code: string; message: string; details?: Record<string, unknown> }; status: number }
  ): Promise<T> {
    if (response.error) {
      handleApiError(
        response.status,
        response.error.code,
        response.error.message,
        response.error.details
      );
      throw new Error(response.error.message);
    }
    return response.data as T;
  };
}

// =============================================================================
// HOOK: useApiCall
// =============================================================================
// Wrapper hook for API calls with automatic error handling
// =============================================================================

interface UseApiCallOptions<T> {
  onSuccess?: (data: T) => void;
  onError?: (error: TenantError) => void;
}

export function useApiCall<T>(options: UseApiCallOptions<T> = {}) {
  const { handleApiError, clearError } = useTenantError();
  const [isLoading, setIsLoading] = useState(false);

  const execute = useCallback(async (
    apiCall: () => Promise<{ data?: T; error?: { code: string; message: string; details?: Record<string, unknown> }; status: number }>
  ): Promise<T | null> => {
    setIsLoading(true);
    clearError();

    try {
      const response = await apiCall();

      if (response.error) {
        const error: TenantError = {
          code: response.error.code,
          status: response.status,
          message: response.error.message,
          details: response.error.details,
          timestamp: new Date().toISOString(),
        };
        handleApiError(response.status, response.error.code, response.error.message, response.error.details);
        options.onError?.(error);
        return null;
      }

      options.onSuccess?.(response.data as T);
      return response.data as T;
    } catch (err) {
      const error: TenantError = {
        code: 'NETWORK_ERROR',
        status: 0,
        message: err instanceof Error ? err.message : 'Unknown error',
        timestamp: new Date().toISOString(),
      };
      handleApiError(0, 'NETWORK_ERROR', error.message);
      options.onError?.(error);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [handleApiError, clearError, options]);

  return { execute, isLoading };
}
