// =============================================================================
// SOLVEREIGN Platform API Client (BFF Layer) - V2 Hardened
// =============================================================================
// Handles HMAC-signed internal requests to FastAPI backend.
// All browser requests go through Next.js API routes that sign requests.
//
// V2 Hardening:
//   - Nonce per request (replay protection)
//   - Body SHA256 hash (payload binding)
//   - Timestamp window (±120s server-side)
//   - Query string canonicalization
//   - Idempotency keys for POST requests
// =============================================================================

import crypto from 'crypto';

// Environment variables (server-side only)
const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || 'http://localhost:8000';
const INTERNAL_SECRET = process.env.SOLVEREIGN_INTERNAL_SECRET || 'dev_secret_change_in_production';

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Generate cryptographically secure nonce (128-bit hex).
 */
export function generateNonce(): string {
  return crypto.randomBytes(16).toString('hex');
}

/**
 * Compute SHA256 hash of body content.
 * Returns empty string for empty/null body.
 */
export function computeBodyHash(body: unknown): string {
  if (body === null || body === undefined) {
    return '';
  }
  const bodyString = typeof body === 'string' ? body : JSON.stringify(body);
  if (!bodyString || bodyString === '{}') {
    return '';
  }
  return crypto.createHash('sha256').update(bodyString, 'utf8').digest('hex');
}

/**
 * Canonicalize path with query string.
 * Sorts query params alphabetically for stable signatures.
 */
export function canonicalizePath(path: string): string {
  // Handle paths that might already be full URLs
  try {
    const url = new URL(path, 'http://localhost');
    const sortedParams = new URLSearchParams([...url.searchParams.entries()].sort());
    const queryString = sortedParams.toString();
    return queryString ? `${url.pathname}?${queryString}` : url.pathname;
  } catch {
    // If URL parsing fails, return path as-is
    return path;
  }
}

// =============================================================================
// SIGNATURE GENERATION (V2 - Hardened)
// =============================================================================

interface SignatureParams {
  method: string;
  path: string;
  body?: unknown;
  tenantCode?: string | null;
  siteCode?: string | null;
  isPlatformAdmin?: boolean;
}

interface SignatureResult {
  signature: string;
  timestamp: number;
  nonce: string;
  bodyHash: string;
  canonicalPath: string;
}

/**
 * Generate HMAC-SHA256 signature for internal requests (V2 Hardened).
 *
 * Canonical format V2:
 *   METHOD|CANONICAL_PATH|TIMESTAMP|NONCE|TENANT_CODE|SITE_CODE|IS_PLATFORM_ADMIN|BODY_SHA256
 *
 * Security features:
 *   - Nonce: unique per request, prevents replay within timestamp window
 *   - Body hash: binds signature to request payload
 *   - Canonical path: sorted query params for stability
 *   - Timestamp: validated server-side (±120s window)
 */
export function generateSignature(params: SignatureParams): SignatureResult {
  const timestamp = Math.floor(Date.now() / 1000);
  const nonce = generateNonce();
  const canonicalPath = canonicalizePath(params.path);

  // Compute body hash for methods with body
  const methodsWithBody = ['POST', 'PUT', 'PATCH'];
  const bodyHash = methodsWithBody.includes(params.method.toUpperCase())
    ? computeBodyHash(params.body)
    : '';

  const canonical = [
    params.method.toUpperCase(),
    canonicalPath,
    timestamp.toString(),
    nonce,
    params.tenantCode || '',
    params.siteCode || '',
    params.isPlatformAdmin ? '1' : '0',
    bodyHash,
  ].join('|');

  const signature = crypto
    .createHmac('sha256', INTERNAL_SECRET)
    .update(canonical)
    .digest('hex');

  return { signature, timestamp, nonce, bodyHash, canonicalPath };
}

// =============================================================================
// IDEMPOTENCY KEY GENERATION
// =============================================================================

/**
 * Generate idempotency key for POST requests.
 * Deterministic keys for known operations, random for others.
 */
export function generateIdempotencyKey(
  operation: string,
  ...identifiers: string[]
): string {
  if (identifiers.length > 0) {
    // Deterministic key for known operations
    return `${operation}:${identifiers.join(':')}`;
  }
  // Random key for unknown operations
  return `${operation}:${crypto.randomUUID()}`;
}

// =============================================================================
// PLATFORM API CLIENT
// =============================================================================

interface FetchOptions {
  method?: string;
  body?: unknown;
  tenantCode?: string | null;
  siteCode?: string | null;
  isPlatformAdmin?: boolean;
  idempotencyKey?: string;
}

interface ApiResponse<T = unknown> {
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  status: number;
  cached?: boolean; // True if returned from idempotency cache
}

/**
 * Make signed request to backend API (V2 Hardened).
 *
 * This function is ONLY for server-side use (API routes).
 * Browser cannot call this directly.
 *
 * Headers sent:
 *   - X-SV-Internal: "1"
 *   - X-SV-Timestamp: Unix timestamp
 *   - X-SV-Nonce: Unique request nonce
 *   - X-SV-Body-SHA256: Hash of request body (for POST/PUT/PATCH)
 *   - X-SV-Signature: HMAC-SHA256 signature
 *   - X-Idempotency-Key: For POST requests (optional)
 */
export async function platformFetch<T = unknown>(
  path: string,
  options: FetchOptions = {}
): Promise<ApiResponse<T>> {
  const {
    method = 'GET',
    body,
    tenantCode = null,
    siteCode = null,
    isPlatformAdmin = true,
    idempotencyKey,
  } = options;

  // Generate V2 signature with nonce and body hash
  const { signature, timestamp, nonce, bodyHash } = generateSignature({
    method,
    path,
    body,
    tenantCode,
    siteCode,
    isPlatformAdmin,
  });

  // Build headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-SV-Internal': '1',
    'X-SV-Timestamp': timestamp.toString(),
    'X-SV-Nonce': nonce,
    'X-SV-Signature': signature,
  };

  // Add body hash header for methods with body
  if (bodyHash) {
    headers['X-SV-Body-SHA256'] = bodyHash;
  }

  // Add idempotency key for ALL write methods (POST, PUT, PATCH, DELETE)
  const writeMethods = ['POST', 'PUT', 'PATCH', 'DELETE'];
  if (idempotencyKey && writeMethods.includes(method.toUpperCase())) {
    headers['X-Idempotency-Key'] = idempotencyKey;
  }

  if (isPlatformAdmin) {
    headers['X-Platform-Admin'] = 'true';
  }
  if (tenantCode) {
    headers['X-Tenant-Code'] = tenantCode;
  }
  if (siteCode) {
    headers['X-Site-Code'] = siteCode;
  }

  try {
    const response = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    });

    const contentType = response.headers.get('content-type');
    let data: T | undefined;

    if (contentType?.includes('application/json')) {
      data = await response.json();
    }

    // Check if response was from idempotency cache
    const cached = response.headers.get('X-Idempotency-Cached') === 'true';

    if (!response.ok) {
      return {
        error: {
          code: `HTTP_${response.status}`,
          message: (data as Record<string, unknown>)?.detail?.toString() || response.statusText,
          details: data as Record<string, unknown>,
        },
        status: response.status,
        cached,
      };
    }

    return { data, status: response.status, cached };
  } catch (error) {
    console.error('Platform API Error:', error);
    return {
      error: {
        code: 'NETWORK_ERROR',
        message: error instanceof Error ? error.message : 'Unknown error',
      },
      status: 500,
    };
  }
}

// =============================================================================
// TYPED API METHODS
// =============================================================================

// Organization types
export interface Organization {
  id: string;
  org_code: string;
  name: string;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface OrganizationWithStatus extends Organization {
  status?: {
    overall_status: 'healthy' | 'degraded' | 'blocked';
    worst_severity: 'S0' | 'S1' | 'S2' | 'S3' | null;
    blocked_count: number;
    degraded_count: number;
  };
  tenants_count?: number;
}

// Tenant types
export interface Tenant {
  id: string;
  tenant_code: string;
  name: string;
  is_active: boolean;
  owner_org_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TenantWithStatus extends Tenant {
  status?: {
    overall_status: 'healthy' | 'degraded' | 'blocked';
    worst_severity: 'S0' | 'S1' | 'S2' | 'S3' | null;
    blocked_count: number;
    degraded_count: number;
  };
  sites_count?: number;
}

// Site types
export interface Site {
  id: string;
  site_code: string;
  name: string;
  is_active: boolean;
  tenant_id: string;
  timezone: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// Entitlement types
export interface Entitlement {
  id: string;
  tenant_id: string;
  pack_id: string;
  is_enabled: boolean;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// Escalation types
export interface Escalation {
  id: string;
  scope_type: 'platform' | 'org' | 'tenant' | 'site';
  scope_id: string | null;
  status: 'healthy' | 'degraded' | 'blocked';
  severity: 'S0' | 'S1' | 'S2' | 'S3';
  reason_code: string;
  reason_message: string;
  fix_steps: string[];
  runbook_link: string;
  details: Record<string, unknown>;
  started_at: string;
  ended_at: string | null;
  resolved_by: string | null;
}

// Status types
export interface PlatformStatus {
  overall_status: 'healthy' | 'degraded' | 'blocked';
  worst_severity: 'S0' | 'S1' | 'S2' | 'S3' | null;
  blocked_count: number;
  degraded_count: number;
  total_active: number;
  escalations: Escalation[];
}

// =============================================================================
// API METHODS (with Idempotency Keys)
// =============================================================================

// Organizations
export const organizationsApi = {
  list: () => platformFetch<Organization[]>('/api/v1/platform/orgs'),

  get: (orgCode: string) =>
    platformFetch<Organization>(`/api/v1/platform/orgs/${orgCode}`),

  create: (data: { org_code: string; name: string; metadata?: Record<string, unknown> }) =>
    platformFetch<Organization>('/api/v1/platform/orgs', {
      method: 'POST',
      body: data,
      idempotencyKey: generateIdempotencyKey('create-org', data.org_code),
    }),

  update: (orgCode: string, data: { name?: string; metadata?: Record<string, unknown>; is_active?: boolean }) =>
    platformFetch<Organization>(`/api/v1/platform/orgs/${orgCode}`, { method: 'PATCH', body: data }),

  getTenants: (orgCode: string) =>
    platformFetch<Tenant[]>(`/api/v1/platform/orgs/${orgCode}/tenants`),

  createTenant: (orgCode: string, data: { tenant_code: string; name: string; metadata?: Record<string, unknown> }) =>
    platformFetch<Tenant>(`/api/v1/platform/orgs/${orgCode}/tenants`, {
      method: 'POST',
      body: data,
      idempotencyKey: generateIdempotencyKey('create-tenant', orgCode, data.tenant_code),
    }),
};

// Tenants
export const tenantsApi = {
  get: (tenantCode: string) =>
    platformFetch<Tenant>(`/api/v1/platform/tenants/${tenantCode}`),

  update: (tenantCode: string, data: { name?: string; metadata?: Record<string, unknown>; is_active?: boolean }) =>
    platformFetch<Tenant>(`/api/v1/platform/tenants/${tenantCode}`, { method: 'PATCH', body: data }),

  getSites: (tenantCode: string) =>
    platformFetch<Site[]>(`/api/v1/platform/tenants/${tenantCode}/sites`),

  createSite: (tenantCode: string, data: { site_code: string; name: string; timezone: string; metadata?: Record<string, unknown> }) =>
    platformFetch<Site>(`/api/v1/platform/tenants/${tenantCode}/sites`, {
      method: 'POST',
      body: data,
      idempotencyKey: generateIdempotencyKey('create-site', tenantCode, data.site_code),
    }),

  getEntitlements: (tenantCode: string) =>
    platformFetch<Entitlement[]>(`/api/v1/platform/tenants/${tenantCode}/entitlements`),

  setEntitlement: (tenantCode: string, packId: string, data: { is_enabled: boolean; config?: Record<string, unknown> }) =>
    platformFetch<Entitlement>(`/api/v1/platform/tenants/${tenantCode}/entitlements/${packId}`, { method: 'PUT', body: data }),
};

// Sites
export const sitesApi = {
  get: (siteId: string) =>
    platformFetch<Site>(`/api/v1/platform/sites/${siteId}`),

  update: (siteId: string, data: { name?: string; timezone?: string; metadata?: Record<string, unknown>; is_active?: boolean }) =>
    platformFetch<Site>(`/api/v1/platform/sites/${siteId}`, { method: 'PATCH', body: data }),
};

// Platform Status & Escalations
export const statusApi = {
  getPlatformStatus: () =>
    platformFetch<PlatformStatus>('/api/v1/platform/status'),

  getEscalations: (scopeType?: string, scopeId?: string) => {
    const params = new URLSearchParams();
    if (scopeType) params.set('scope_type', scopeType);
    if (scopeId) params.set('scope_id', scopeId);
    const query = params.toString() ? `?${params.toString()}` : '';
    return platformFetch<Escalation[]>(`/api/v1/platform/escalations${query}`);
  },

  recordEscalation: (data: {
    scope_type: 'platform' | 'org' | 'tenant' | 'site';
    scope_id?: string | null;
    reason_code: string;
    details?: Record<string, unknown>;
  }) =>
    platformFetch<Escalation>('/api/v1/platform/escalations', {
      method: 'POST',
      body: data,
      idempotencyKey: generateIdempotencyKey('record-escalation', data.scope_type, data.scope_id || 'platform', data.reason_code),
    }),

  resolveEscalation: (data: {
    escalation_id: string;
    comment: string;
    incident_ref?: string;
  }) =>
    platformFetch<{ resolved_count: number }>(`/api/v1/platform/escalations/${data.escalation_id}/resolve`, {
      method: 'POST',
      body: {
        comment: data.comment,
        incident_ref: data.incident_ref,
      },
    }),
};

// Security Events
export const securityApi = {
  getEvents: (tenantId?: string, limit?: number) => {
    const params = new URLSearchParams();
    if (tenantId) params.set('tenant_id', tenantId);
    if (limit) params.set('limit', limit.toString());
    const query = params.toString() ? `?${params.toString()}` : '';
    return platformFetch<Array<{
      id: string;
      event_type: string;
      severity: string;
      source_ip: string;
      tenant_id: string | null;
      user_id: string | null;
      request_path: string;
      request_method: string;
      details: Record<string, unknown>;
      created_at: string;
    }>>(`/api/v1/platform/security-events${query}`);
  },
};

// =============================================================================
// DISPATCHER COCKPIT API (Wien Pilot MVP)
// =============================================================================

// Run types
export interface DispatcherRunSummary {
  run_id: string;
  week_id: string;
  timestamp: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'BLOCKED' | 'PENDING';
  tenant_code: string;
  site_code: string;
  headcount: number;
  coverage_percent: number;
  audit_pass_count: number;
  audit_total: number;
  evidence_path: string | null;
  kpi_drift_status: string;
  published: boolean;
  published_at: string | null;
  published_by: string | null;
  locked: boolean;
  locked_at: string | null;
  locked_by: string | null;
  notes: string;
}

export interface AuditCheckResult {
  check_name: string;
  status: 'PASS' | 'FAIL' | 'WARN';
  violation_count: number;
  details: Record<string, unknown> | null;
}

export interface KPISummary {
  headcount: number;
  coverage_percent: number;
  fte_ratio: number;
  pt_ratio: number;
  runtime_seconds: number;
  drift_status: string;
}

export interface DispatcherRunDetail {
  run_id: string;
  week_id: string;
  timestamp: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'BLOCKED' | 'PENDING';
  tenant_code: string;
  site_code: string;
  headcount: number;
  coverage_percent: number;
  audit_results: AuditCheckResult[];
  kpis: KPISummary;
  evidence_path: string | null;
  evidence_hash: string | null;
  published: boolean;
  published_at: string | null;
  published_by: string | null;
  locked: boolean;
  locked_at: string | null;
  locked_by: string | null;
  notes: string;
}

export interface DispatcherSystemStatus {
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  publish_enabled: boolean;
  lock_enabled: boolean;
  shadow_mode_only: boolean;
  latest_run: DispatcherRunSummary | null;
  pending_repairs: number;
  active_incidents: number;
}

export interface PublishLockResponse {
  success: boolean;
  run_id: string;
  status: string;
  audit_event_id: string | null;
  evidence_hash: string | null;
  message: string;
  blocked_reason: string | null;
}

export interface RepairResponse {
  request_id: string;
  run_id: string;
  status: string;
  message: string;
}

// Dispatcher API (requires tenant/site context headers)
export const dispatcherApi = {
  /**
   * List runs for a site.
   * Requires X-Tenant-Code and X-Site-Code headers.
   */
  listRuns: (tenantCode: string, siteCode: string, limit = 20, statusFilter?: string) => {
    const params = new URLSearchParams();
    params.set('limit', limit.toString());
    if (statusFilter) params.set('status', statusFilter);
    const query = params.toString() ? `?${params.toString()}` : '';
    return platformFetch<{ runs: DispatcherRunSummary[]; total: number }>(
      `/api/v1/platform/dispatcher/runs${query}`,
      { tenantCode, siteCode, isPlatformAdmin: false }
    );
  },

  /**
   * Get run detail with audit results and KPIs.
   */
  getRun: (tenantCode: string, siteCode: string, runId: string) =>
    platformFetch<DispatcherRunDetail>(
      `/api/v1/platform/dispatcher/runs/${runId}`,
      { tenantCode, siteCode, isPlatformAdmin: false }
    ),

  /**
   * Publish a run (requires approval).
   */
  publishRun: (
    tenantCode: string,
    siteCode: string,
    runId: string,
    data: {
      approver_id: string;
      approver_role: 'dispatcher' | 'ops_lead' | 'platform_admin';
      reason: string;
      override_warn?: boolean;
    }
  ) =>
    platformFetch<PublishLockResponse>(
      `/api/v1/platform/dispatcher/runs/${runId}/publish`,
      {
        method: 'POST',
        body: data,
        tenantCode,
        siteCode,
        isPlatformAdmin: false,
        idempotencyKey: generateIdempotencyKey('publish-run', tenantCode, siteCode, runId),
      }
    ),

  /**
   * Lock a published run for export.
   */
  lockRun: (
    tenantCode: string,
    siteCode: string,
    runId: string,
    data: {
      approver_id: string;
      approver_role: 'dispatcher' | 'ops_lead' | 'platform_admin';
      reason: string;
    }
  ) =>
    platformFetch<PublishLockResponse>(
      `/api/v1/platform/dispatcher/runs/${runId}/lock`,
      {
        method: 'POST',
        body: data,
        tenantCode,
        siteCode,
        isPlatformAdmin: false,
        idempotencyKey: generateIdempotencyKey('lock-run', tenantCode, siteCode, runId),
      }
    ),

  /**
   * Request repair for a run (sick-call/no-show).
   */
  requestRepair: (
    tenantCode: string,
    siteCode: string,
    runId: string,
    data: {
      driver_id: string;
      driver_name: string;
      absence_type: 'sick' | 'vacation' | 'no_show';
      affected_tours: string[];
      urgency?: 'critical' | 'high' | 'normal';
      notes?: string;
    }
  ) =>
    platformFetch<RepairResponse>(
      `/api/v1/platform/dispatcher/runs/${runId}/repair`,
      {
        method: 'POST',
        body: data,
        tenantCode,
        siteCode,
        isPlatformAdmin: false,
        idempotencyKey: generateIdempotencyKey(
          'request-repair',
          tenantCode,
          siteCode,
          runId,
          data.driver_id,
          data.absence_type
        ),
      }
    ),

  /**
   * Get system status (kill switch, publish/lock state).
   */
  getStatus: (tenantCode: string, siteCode: string) =>
    platformFetch<DispatcherSystemStatus>(
      '/api/v1/platform/dispatcher/status',
      { tenantCode, siteCode, isPlatformAdmin: false }
    ),

  /**
   * Get evidence checksums for a run.
   */
  getEvidenceChecksums: (tenantCode: string, siteCode: string, runId: string) =>
    platformFetch<{ run_id: string; checksums: Record<string, string> }>(
      `/api/v1/platform/dispatcher/evidence/${runId}/checksums`,
      { tenantCode, siteCode, isPlatformAdmin: false }
    ),

  /**
   * Get evidence download URL.
   * Note: For actual download, use a direct link or streaming endpoint.
   */
  getEvidenceUrl: (tenantCode: string, siteCode: string, runId: string) =>
    `/api/platform/dispatcher/evidence/${runId}/download?tenant=${tenantCode}&site=${siteCode}`,
};
