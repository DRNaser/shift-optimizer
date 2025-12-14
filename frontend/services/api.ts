// API Service for SHIFT OPTIMIZER
// Connects to new Python FastAPI backend

import {
  ScheduleRequest,
  ScheduleResponse,
  HealthResponse,
  ApiError
} from '../types';

const API_BASE = 'http://localhost:8000/api/v1';

// =============================================================================
// HEALTH CHECK
// =============================================================================

export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw createApiError(response);
  }
  return response.json();
}

// =============================================================================
// SCHEDULE
// =============================================================================

export async function createSchedule(request: ScheduleRequest): Promise<ScheduleResponse> {
  const response = await fetch(`${API_BASE}/schedule`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw await createApiError(response);
  }

  return response.json();
}

// =============================================================================
// CONSTRAINTS
// =============================================================================

export async function getConstraints(): Promise<Record<string, Record<string, number | boolean>>> {
  const response = await fetch(`${API_BASE}/constraints`);
  if (!response.ok) {
    throw createApiError(response);
  }
  return response.json();
}

// =============================================================================
// ERROR HANDLING
// =============================================================================

async function createApiError(response: Response): Promise<ApiError> {
  let message = `HTTP ${response.status}: ${response.statusText}`;
  let details: string[] = [];

  try {
    const body = await response.json();
    if (body.detail) {
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    }
    if (body.details) {
      details = Array.isArray(body.details) ? body.details : [body.details];
    }
  } catch {
    // Ignore JSON parse errors
  }

  return {
    status: 'error',
    message,
    details,
  };
}

// Legacy export for backward compatibility
export const optimizeShiftsApi = createSchedule;
