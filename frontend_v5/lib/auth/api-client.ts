// =============================================================================
// SOLVEREIGN - Authenticated API Client (Browser)
// =============================================================================
//
// !!! DEPRECATED (V4.4.0) !!!
// ===========================
// This module is DEPRECATED as of V4.4.0 (2026-01-09).
// Internal RBAC with HttpOnly session cookies is now the default.
//
// MIGRATION:
// - Portal Admin Dashboard uses BFF routes (app/api/portal-admin/*)
// - Session cookies are forwarded automatically
// - No Bearer tokens needed
//
// This file is kept for reference only. DO NOT USE for new development.
//
// =============================================================================
// Original documentation (historical):
// Browser-side API client that injects MSAL Bearer tokens into requests.
// Uses the useAuth() hook to acquire tokens silently.
// =============================================================================

'use client';

import { useCallback, useMemo } from 'react';
import { useAuth, type AuthUser } from './auth-context';

// =============================================================================
// TYPES
// =============================================================================

export interface ApiResponse<T = unknown> {
  data?: T;
  error?: ApiError;
  status: number;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface FetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
}

// =============================================================================
// HOOK: useAuthenticatedFetch
// =============================================================================

/**
 * Hook that provides an authenticated fetch function.
 * Automatically injects MSAL Bearer token into requests.
 */
export function useAuthenticatedFetch() {
  const { getAccessToken, isAuthenticated, user } = useAuth();

  const authFetch = useCallback(async <T = unknown>(
    path: string,
    options: FetchOptions = {}
  ): Promise<ApiResponse<T>> => {
    const { method = 'GET', body, headers = {} } = options;

    // Get access token
    const token = await getAccessToken();
    if (!token) {
      return {
        error: {
          code: 'AUTH_REQUIRED',
          message: 'Authentication required. Please sign in.',
        },
        status: 401,
      };
    }

    // Build request headers
    const requestHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...headers,
    };

    try {
      const response = await fetch(path, {
        method,
        headers: requestHeaders,
        body: body ? JSON.stringify(body) : undefined,
      });

      const contentType = response.headers.get('content-type');
      let data: T | undefined;

      if (contentType?.includes('application/json')) {
        data = await response.json();
      }

      if (!response.ok) {
        return {
          error: parseApiError(response.status, data),
          status: response.status,
        };
      }

      return { data, status: response.status };
    } catch (error) {
      console.error('API fetch error:', error);
      return {
        error: {
          code: 'NETWORK_ERROR',
          message: error instanceof Error ? error.message : 'Network error',
        },
        status: 0,
      };
    }
  }, [getAccessToken]);

  return {
    authFetch,
    isAuthenticated,
    user,
  };
}

// =============================================================================
// HOOK: useApi (Convenience Methods)
// =============================================================================

/**
 * Hook that provides typed API methods with authentication.
 */
export function useApi() {
  const { authFetch, isAuthenticated, user } = useAuthenticatedFetch();

  const api = useMemo(() => ({
    // Current user info
    me: {
      get: () => authFetch<CurrentUserResponse>('/api/v1/me'),
    },

    // Plans
    plans: {
      get: (planId: string) => authFetch<PlanResponse>(`/api/v1/plans/${planId}`),

      solve: (forecastVersionId: number, config?: SolveConfig) => authFetch<SolveResponse>(
        '/api/v1/plans/solve',
        { method: 'POST', body: { forecast_version_id: forecastVersionId, ...config } }
      ),

      approve: (planId: string, reason: string) => authFetch<ApproveResponse>(
        `/api/v1/plans/${planId}/approve`,
        { method: 'POST', body: { reason } }
      ),

      publish: (planId: string, request: PublishRequest) => authFetch<PublishResponse>(
        `/api/v1/plans/${planId}/publish`,
        { method: 'POST', body: request }
      ),

      repair: (planId: string, request: RepairRequest) => authFetch<RepairResponse>(
        `/api/v1/plans/${planId}/repair`,
        { method: 'POST', body: request }
      ),

      getSnapshots: (planId: string) => authFetch<SnapshotListResponse>(
        `/api/v1/plans/${planId}/snapshots`
      ),

      getFreezeStatus: (planId: string) => authFetch<FreezeStatusResponse>(
        `/api/v1/plans/${planId}/freeze-status`
      ),
    },

    // Solver runs
    runs: {
      list: (params?: ListRunsParams) => {
        const query = params ? `?${new URLSearchParams(params as Record<string, string>)}` : '';
        return authFetch<RunsListResponse>(`/api/v1/runs${query}`);
      },
      get: (runId: string) => authFetch<RunDetailResponse>(`/api/v1/runs/${runId}`),
      getPlan: (runId: string) => authFetch<RunPlanResponse>(`/api/v1/runs/${runId}/plan`),
    },

    // Forecasts
    forecasts: {
      list: () => authFetch<ForecastsListResponse>('/api/v1/forecasts'),
      get: (id: string) => authFetch<ForecastResponse>(`/api/v1/forecasts/${id}`),
      ingest: (data: ForecastIngestRequest) => authFetch<ForecastIngestResponse>(
        '/api/v1/forecasts/ingest',
        { method: 'POST', body: data }
      ),
    },

    // Health
    health: {
      check: () => authFetch<HealthResponse>('/api/v1/health'),
    },
  }), [authFetch]);

  return {
    api,
    isAuthenticated,
    user,
  };
}

// =============================================================================
// API TYPES
// =============================================================================

// Current User
export interface CurrentUserResponse {
  id: string;
  email: string;
  name: string;
  tenant_id: number;
  site_id: number;
  roles: string[];
}

// Plans
export interface PlanResponse {
  id: string;
  tenant_id: number;
  site_id: number;
  forecast_version_id: number;
  plan_state: string;
  created_at: string;
  updated_at: string;
  current_snapshot_id?: string;
}

export interface SolveConfig {
  seed?: number;
  time_limit_seconds?: number;
  workers?: number;
}

export interface SolveResponse {
  plan_id: string;
  status: string;
  message: string;
}

export interface ApproveResponse {
  success: boolean;
  plan_id: string;
  approved_by: string;
  approved_at: string;
}

export interface PublishRequest {
  reason: string;
  force_during_freeze?: boolean;
  force_reason?: string;
}

export interface PublishResponse {
  success: boolean;
  snapshot_id: string;
  version_number: number;
  published_by: string;
  published_at: string;
  forced_during_freeze?: boolean;
  freeze_until?: string;
}

export interface RepairRequest {
  reason: string;
  source_snapshot_id?: string;
}

export interface RepairResponse {
  success: boolean;
  new_plan_id: string;
  source_snapshot_id: string;
  created_at: string;
}

// Snapshots
export interface SnapshotListResponse {
  snapshots: PlanSnapshot[];
}

export interface PlanSnapshot {
  id: string;
  plan_version_id: string;
  version_number: number;
  snapshot_status: 'ACTIVE' | 'SUPERSEDED' | 'ARCHIVED';
  published_by: string;
  published_at: string;
  freeze_until?: string;
  is_frozen: boolean;
  input_hash: string;
  output_hash: string;
  is_legacy: boolean;  // V3.7.2: True if payload is empty
  kpis?: SnapshotKPIs;
}

export interface SnapshotKPIs {
  total_stops: number;
  assigned_stops: number;
  vehicles_used: number;
  total_distance_km: number;
  total_duration_min: number;
}

// Freeze Status
export interface FreezeStatusResponse {
  plan_id: string;
  is_frozen: boolean;
  freeze_until?: string;
  minutes_remaining?: number;
  can_force: boolean;
}

// Runs
export interface ListRunsParams {
  status?: string;
  limit?: string;
  offset?: string;
}

export interface RunsListResponse {
  runs: RunSummary[];
  total: number;
}

export interface RunSummary {
  run_id: string;
  status: string;
  created_at: string;
  completed_at?: string;
}

export interface RunDetailResponse {
  run_id: string;
  status: string;
  phase?: string;
  progress?: number;
  created_at: string;
  completed_at?: string;
}

export interface RunPlanResponse {
  run_id: string;
  assignments: unknown[];
  unassigned_tours: unknown[];
  stats: unknown;
}

// Forecasts
export interface ForecastsListResponse {
  forecasts: ForecastSummary[];
}

export interface ForecastSummary {
  id: string;
  week_anchor_date: string;
  status: string;
  created_at: string;
}

export interface ForecastResponse {
  id: string;
  week_anchor_date: string;
  status: string;
  tours_count: number;
  created_at: string;
}

export interface ForecastIngestRequest {
  raw_text: string;
  source: string;
  week_anchor_date: string;
  notes?: string;
}

export interface ForecastIngestResponse {
  forecast_version_id: number;
  tours_count: number;
  message: string;
}

// Health
export interface HealthResponse {
  status: string;
  version: string;
  database: string;
}

// =============================================================================
// HELPERS
// =============================================================================

function parseApiError(status: number, data: unknown): ApiError {
  const errorData = data as Record<string, unknown> | undefined;

  // Handle common error codes
  switch (status) {
    case 401:
      return {
        code: 'UNAUTHORIZED',
        message: 'Authentication required',
        details: errorData,
      };
    case 403:
      // Check for specific error codes
      if (errorData?.error === 'APP_TOKEN_NOT_ALLOWED') {
        return {
          code: 'APP_TOKEN_NOT_ALLOWED',
          message: 'Service accounts cannot perform this action',
          details: errorData,
        };
      }
      return {
        code: 'FORBIDDEN',
        message: errorData?.detail?.toString() || 'Access denied',
        details: errorData,
      };
    case 409:
      // Freeze window conflict
      if (errorData?.error === 'FREEZE_WINDOW_ACTIVE') {
        return {
          code: 'FREEZE_WINDOW_ACTIVE',
          message: errorData?.message?.toString() || 'Cannot publish during freeze window',
          details: errorData,
        };
      }
      return {
        code: 'CONFLICT',
        message: errorData?.detail?.toString() || 'Conflict',
        details: errorData,
      };
    case 422:
      return {
        code: 'VALIDATION_ERROR',
        message: formatValidationError(errorData),
        details: errorData,
      };
    default:
      return {
        code: `HTTP_${status}`,
        message: errorData?.detail?.toString() || `Request failed with status ${status}`,
        details: errorData,
      };
  }
}

function formatValidationError(data: unknown): string {
  const errorData = data as { detail?: Array<{ loc?: string[]; msg?: string }> } | undefined;

  if (errorData?.detail && Array.isArray(errorData.detail)) {
    return errorData.detail
      .map((e) => `${e.loc?.join('.') || 'field'}: ${e.msg || 'invalid'}`)
      .join('; ');
  }

  return 'Validation failed';
}
