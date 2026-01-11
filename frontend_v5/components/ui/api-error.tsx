// =============================================================================
// SOLVEREIGN API Error Display (V4.7)
// =============================================================================
// Maps API error codes to user-friendly messages.
// Used consistently across all pack and platform pages.
// =============================================================================

'use client';

import Link from 'next/link';
import { AlertTriangle, Lock, Building2, Package, ArrowRight, RefreshCw } from 'lucide-react';

// Error code to friendly message mapping
const ERROR_MESSAGES: Record<string, { title: string; message: string; icon: React.ComponentType<{ className?: string }>; action?: { label: string; href: string } }> = {
  CONTEXT_REQUIRED: {
    title: 'Tenant Context Required',
    message: 'You need to select a tenant before accessing this feature.',
    icon: Building2,
    action: { label: 'Select Tenant', href: '/select-tenant' },
  },
  PACK_DISABLED: {
    title: 'Pack Not Available',
    message: 'This pack is not enabled for the current tenant. Contact your administrator.',
    icon: Package,
  },
  ROUTE_NOT_AVAILABLE: {
    title: 'Feature Not Available',
    message: 'This feature is not available for your account or tenant.',
    icon: Lock,
  },
  UNAUTHORIZED: {
    title: 'Not Authorized',
    message: 'You do not have permission to access this resource.',
    icon: Lock,
  },
  NOT_FOUND: {
    title: 'Not Found',
    message: 'The requested resource could not be found.',
    icon: AlertTriangle,
  },
  TENANT_NOT_FOUND: {
    title: 'Tenant Not Found',
    message: 'The specified tenant does not exist or is not accessible.',
    icon: Building2,
  },
  SITE_TENANT_MISMATCH: {
    title: 'Invalid Site',
    message: 'The selected site does not belong to the specified tenant.',
    icon: AlertTriangle,
  },
  SESSION_EXPIRED: {
    title: 'Session Expired',
    message: 'Your session has expired. Please log in again.',
    icon: Lock,
    action: { label: 'Log In', href: '/platform/login' },
  },
};

interface ApiErrorProps {
  code?: string;
  message?: string;
  showBackLink?: boolean;
  backHref?: string;
  onRetry?: () => void;
}

export function ApiError({
  code = 'UNKNOWN',
  message,
  showBackLink = true,
  backHref = '/platform/home',
  onRetry,
}: ApiErrorProps) {
  const errorConfig = ERROR_MESSAGES[code] || {
    title: 'Error',
    message: message || 'An unexpected error occurred.',
    icon: AlertTriangle,
  };

  const Icon = errorConfig.icon;

  return (
    <div className="min-h-[400px] flex items-center justify-center p-8">
      <div className="max-w-md w-full bg-slate-800 border border-slate-700 rounded-lg p-6 text-center">
        <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-red-500/20 mb-4">
          <Icon className="h-8 w-8 text-red-400" />
        </div>

        <h2 className="text-xl font-bold text-white mb-2">
          {errorConfig.title}
        </h2>

        <p className="text-slate-400 mb-6">
          {message || errorConfig.message}
        </p>

        <div className="flex flex-col gap-3">
          {/* Primary action (from error config) */}
          {errorConfig.action && (
            <Link
              href={errorConfig.action.href}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-emerald-600 text-white rounded-md hover:bg-emerald-500 transition-colors"
            >
              {errorConfig.action.label}
            </Link>
          )}

          {/* Retry button */}
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 text-white rounded-md hover:bg-slate-600 transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
              Try Again
            </button>
          )}

          {/* Back link */}
          {showBackLink && (
            <Link
              href={backHref}
              className="inline-flex items-center justify-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
            >
              <ArrowRight className="h-4 w-4 rotate-180" />
              Back to Home
            </Link>
          )}
        </div>

        {/* Error code (for debugging) */}
        <p className="mt-4 text-xs text-slate-600">
          Error code: {code}
        </p>
      </div>
    </div>
  );
}

// Hook for handling API errors
export function useApiError() {
  const handleError = (error: unknown): { code: string; message: string } => {
    if (error instanceof Response) {
      return { code: 'HTTP_ERROR', message: `HTTP ${error.status}` };
    }

    if (typeof error === 'object' && error !== null) {
      const err = error as { detail?: { error_code?: string; message?: string } | string; error_code?: string; message?: string };

      // Handle FastAPI error format
      if (err.detail) {
        if (typeof err.detail === 'object') {
          return {
            code: err.detail.error_code || 'UNKNOWN',
            message: err.detail.message || 'An error occurred',
          };
        }
        return { code: 'UNKNOWN', message: String(err.detail) };
      }

      return {
        code: err.error_code || 'UNKNOWN',
        message: err.message || 'An error occurred',
      };
    }

    return { code: 'UNKNOWN', message: String(error) };
  };

  return { handleError };
}
