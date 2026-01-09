// =============================================================================
// SOLVEREIGN Tenant API Client (BFF Layer) - V2 Hardened
// =============================================================================
// Handles HMAC-signed internal requests for TENANT-SCOPED operations.
// Mirrors platform-api.ts but with tenant/site context headers.
//
// KEY DIFFERENCE from platform-api.ts:
//   - isPlatformAdmin = false
//   - REQUIRES tenantCode and siteCode
//   - Tenant-scoped endpoints only
// =============================================================================

import crypto from 'crypto';

// Environment variables (server-side only)
const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || 'http://localhost:8000';
const INTERNAL_SECRET = process.env.SOLVEREIGN_INTERNAL_SECRET || 'dev_secret_change_in_production';

// =============================================================================
// UTILITY FUNCTIONS (shared with platform-api.ts)
// =============================================================================

export function generateNonce(): string {
  return crypto.randomBytes(16).toString('hex');
}

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

export function canonicalizePath(path: string): string {
  try {
    const url = new URL(path, 'http://localhost');
    const sortedParams = new URLSearchParams([...url.searchParams.entries()].sort());
    const queryString = sortedParams.toString();
    return queryString ? `${url.pathname}?${queryString}` : url.pathname;
  } catch {
    return path;
  }
}

// =============================================================================
// SIGNATURE GENERATION (V2 - Tenant Context)
// =============================================================================

interface SignatureParams {
  method: string;
  path: string;
  body?: unknown;
  tenantCode: string;
  siteCode: string;
}

interface SignatureResult {
  signature: string;
  timestamp: number;
  nonce: string;
  bodyHash: string;
  canonicalPath: string;
}

/**
 * Generate HMAC-SHA256 signature for tenant-scoped requests.
 *
 * Canonical format V2:
 *   METHOD|CANONICAL_PATH|TIMESTAMP|NONCE|TENANT_CODE|SITE_CODE|IS_PLATFORM_ADMIN|BODY_SHA256
 *
 * Note: IS_PLATFORM_ADMIN is always "0" for tenant requests.
 */
export function generateTenantSignature(params: SignatureParams): SignatureResult {
  const timestamp = Math.floor(Date.now() / 1000);
  const nonce = generateNonce();
  const canonicalPath = canonicalizePath(params.path);

  const methodsWithBody = ['POST', 'PUT', 'PATCH'];
  const bodyHash = methodsWithBody.includes(params.method.toUpperCase())
    ? computeBodyHash(params.body)
    : '';

  const canonical = [
    params.method.toUpperCase(),
    canonicalPath,
    timestamp.toString(),
    nonce,
    params.tenantCode,
    params.siteCode,
    '0', // isPlatformAdmin = false for tenant requests
    bodyHash,
  ].join('|');

  const signature = crypto
    .createHmac('sha256', INTERNAL_SECRET)
    .update(canonical)
    .digest('hex');

  return { signature, timestamp, nonce, bodyHash, canonicalPath };
}

/**
 * Generate idempotency key for tenant operations.
 */
export function generateTenantIdempotencyKey(
  tenantCode: string,
  siteCode: string,
  operation: string,
  ...identifiers: string[]
): string {
  const parts = [tenantCode, siteCode, operation, ...identifiers].filter(Boolean);
  return parts.join(':');
}

// =============================================================================
// TENANT API CLIENT
// =============================================================================

interface TenantFetchOptions {
  method?: string;
  body?: unknown;
  tenantCode: string;
  siteCode: string;
  idempotencyKey?: string;
}

export interface TenantApiResponse<T = unknown> {
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  status: number;
  cached?: boolean;
}

/**
 * Make signed request to backend API for TENANT-SCOPED operations.
 *
 * This function is ONLY for server-side use (API routes).
 * Browser calls BFF routes which call this function.
 */
export async function tenantFetch<T = unknown>(
  path: string,
  options: TenantFetchOptions
): Promise<TenantApiResponse<T>> {
  const {
    method = 'GET',
    body,
    tenantCode,
    siteCode,
    idempotencyKey,
  } = options;

  // Generate V2 signature with tenant/site context
  const { signature, timestamp, nonce, bodyHash } = generateTenantSignature({
    method,
    path,
    body,
    tenantCode,
    siteCode,
  });

  // Build headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-SV-Internal': '1',
    'X-SV-Timestamp': timestamp.toString(),
    'X-SV-Nonce': nonce,
    'X-SV-Signature': signature,
    'X-Tenant-Code': tenantCode,
    'X-Site-Code': siteCode,
    // Explicitly NOT a platform admin
    'X-Platform-Admin': 'false',
  };

  if (bodyHash) {
    headers['X-SV-Body-SHA256'] = bodyHash;
  }

  if (idempotencyKey && method.toUpperCase() === 'POST') {
    headers['X-Idempotency-Key'] = idempotencyKey;
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
    console.error('Tenant API Error:', error);
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
// TENANT-SCOPED TYPES
// =============================================================================

// Tenant Status (for Status Banner)
export interface TenantStatus {
  tenant_code: string;
  site_code: string;
  overall_status: 'healthy' | 'degraded' | 'blocked';
  is_write_blocked: boolean;
  reason_code: string | null;
  reason_message: string | null;
  escalation_id: string | null;
  blocked_since: string | null;
}

// Import/Stop types
export interface StopImportJob {
  id: string;
  tenant_code: string;
  site_code: string;
  filename: string;
  status: 'PENDING' | 'VALIDATING' | 'VALIDATED' | 'ACCEPTED' | 'REJECTED' | 'FAILED';
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  validation_errors: ValidationError[];
  created_at: string;
  validated_at: string | null;
  accepted_at: string | null;
}

export interface ValidationError {
  row: number;
  field: string;
  error_code: string;
  message: string;
}

// Team types
export interface Team {
  id: string;
  team_code: string;
  driver_1_id: string;
  driver_1_name: string;
  driver_2_id: string | null;
  driver_2_name: string | null;
  team_size: 1 | 2;
  skills: string[];
  is_active: boolean;
}

export interface TeamDailyAssignment {
  id: string;
  date: string;
  team_id: string;
  team: Team;
  vehicle_id: string | null;
  shift_start: string;
  shift_end: string;
  requires_two_person: boolean;
  demand_status: 'MATCHED' | 'MISMATCH_UNDER' | 'MISMATCH_OVER' | null;
}

// Scenario types
export interface RoutingScenario {
  id: string;
  tenant_code: string;
  site_code: string;
  vertical: 'MEDIAMARKT' | 'HDL_PLUS';
  plan_date: string;
  status: 'CREATED' | 'SOLVING' | 'SOLVED' | 'FAILED';
  input_hash: string;
  stops_count: number;
  vehicles_count: number;
  created_at: string;
  solved_at: string | null;
  // Blueprint v6 Contract Decision (Option D): Backend must provide this
  latest_plan_id: string | null;
}

export interface RoutingPlan {
  id: string;
  scenario_id: string;
  status: 'QUEUED' | 'SOLVING' | 'SOLVED' | 'AUDITED' | 'DRAFT' | 'LOCKED' | 'FAILED' | 'SUPERSEDED';
  seed: number | null;
  solver_config_hash: string;
  output_hash: string | null;
  total_vehicles: number | null;
  total_distance_km: number | null;
  total_duration_min: number | null;
  unassigned_count: number | null;
  on_time_percentage: number | null;
  created_at: string;
  locked_at: string | null;
  locked_by: string | null;
}

export interface AuditResult {
  check_name: string;
  status: 'PASS' | 'FAIL' | 'WARN' | 'SKIP';
  violation_count: number;
  details: Record<string, unknown>;
}

export interface EvidencePack {
  id: string;
  plan_id: string;
  artifact_url: string;
  sha256_hash: string;
  created_at: string;
  size_bytes: number;
}

export interface RepairEvent {
  id: string;
  plan_id: string;
  event_type: 'NO_SHOW' | 'DELAY' | 'VEHICLE_DOWN' | 'MANUAL';
  affected_stop_ids: string[];
  initiated_by: string;
  initiated_at: string;
  repair_plan_id: string | null;
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
}

// =============================================================================
// UI STATUS DERIVATION (Blueprint v6 - Korrektur 7)
// =============================================================================
// PlanStatus is DERIVED from backend fields, NOT a separate backend field.
// Source of truth:
// - plan.status → base status
// - auditResult → AUDIT_FAIL if any check has status='FAIL'
// - freezeState → adds FROZEN badge if freeze_status != 'NONE'
// =============================================================================

/**
 * UI-friendly status for display in the frontend.
 * Derived from backend fields, not stored separately.
 */
export type UIPlanStatus =
  | 'QUEUED'       // Waiting to solve
  | 'SOLVING'      // Currently solving
  | 'SOLVED'       // Solver finished
  | 'AUDIT_PASS'   // All audits passed
  | 'AUDIT_FAIL'   // At least one audit failed
  | 'AUDIT_WARN'   // All passed but some warnings
  | 'DRAFT'        // Ready for lock
  | 'LOCKED'       // Immutable
  | 'FROZEN'       // Has frozen stops
  | 'FAILED'       // Solver failed
  | 'SUPERSEDED';  // Replaced by newer plan

export interface AuditSummary {
  all_passed: boolean;
  checks_run: number;
  checks_passed: number;
  checks_warn: number;
  checks_fail: number;
  results: AuditResult[];
}

export interface FreezeState {
  plan_id: string;
  total_stops: number;
  frozen_stops: number;
  unfrozen_stops: number;
  freeze_status: 'NONE' | 'PARTIAL' | 'FULL';
  frozen_stop_ids: string[];
}

/**
 * Derive UI-friendly status from backend fields.
 *
 * Priority order:
 * 1. FAILED, SUPERSEDED (terminal states)
 * 2. LOCKED (with optional FROZEN badge)
 * 3. AUDIT_FAIL (blocks lock)
 * 4. AUDIT_PASS / AUDIT_WARN (ready for lock)
 * 5. SOLVING, QUEUED (in progress)
 */
export function deriveUIStatus(
  plan: RoutingPlan,
  auditSummary?: AuditSummary | null,
  freezeState?: FreezeState | null
): { status: UIPlanStatus; badges: string[] } {
  const badges: string[] = [];

  // Terminal states
  if (plan.status === 'FAILED') {
    return { status: 'FAILED', badges };
  }
  if (plan.status === 'SUPERSEDED') {
    return { status: 'SUPERSEDED', badges };
  }

  // Add FROZEN badge if applicable
  if (freezeState && freezeState.freeze_status !== 'NONE') {
    badges.push(`FROZEN (${freezeState.frozen_stops}/${freezeState.total_stops})`);
  }

  // LOCKED state
  if (plan.status === 'LOCKED') {
    return { status: 'LOCKED', badges };
  }

  // Check audit results if available
  if (auditSummary) {
    if (auditSummary.checks_fail > 0) {
      return { status: 'AUDIT_FAIL', badges };
    }
    if (auditSummary.checks_warn > 0 && auditSummary.all_passed) {
      return { status: 'AUDIT_WARN', badges };
    }
    if (auditSummary.all_passed) {
      return { status: 'AUDIT_PASS', badges };
    }
  }

  // Plan status direct mapping
  if (plan.status === 'AUDITED' || plan.status === 'DRAFT') {
    return { status: 'DRAFT', badges };
  }
  if (plan.status === 'SOLVED') {
    return { status: 'SOLVED', badges };
  }
  if (plan.status === 'SOLVING') {
    return { status: 'SOLVING', badges };
  }
  if (plan.status === 'QUEUED') {
    return { status: 'QUEUED', badges };
  }

  // Default
  return { status: plan.status as UIPlanStatus, badges };
}

/**
 * Get CSS class for status badge.
 */
export function getStatusColor(status: UIPlanStatus): string {
  switch (status) {
    case 'LOCKED':
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
    case 'AUDIT_PASS':
    case 'DRAFT':
      return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200';
    case 'AUDIT_WARN':
      return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
    case 'AUDIT_FAIL':
    case 'FAILED':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
    case 'SOLVING':
    case 'QUEUED':
      return 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200';
    case 'SUPERSEDED':
      return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200';
    case 'FROZEN':
      return 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

/**
 * Get human-readable label for status.
 */
export function getStatusLabel(status: UIPlanStatus): string {
  switch (status) {
    case 'QUEUED': return 'Warteschlange';
    case 'SOLVING': return 'Berechnung läuft';
    case 'SOLVED': return 'Berechnet';
    case 'AUDIT_PASS': return 'Audit OK';
    case 'AUDIT_FAIL': return 'Audit FAIL';
    case 'AUDIT_WARN': return 'Audit WARN';
    case 'DRAFT': return 'Entwurf';
    case 'LOCKED': return 'Gesperrt';
    case 'FROZEN': return 'Eingefroren';
    case 'FAILED': return 'Fehlgeschlagen';
    case 'SUPERSEDED': return 'Ersetzt';
    default: return status;
  }
}

// =============================================================================
// API METHODS (Tenant-Scoped)
// =============================================================================

export function createTenantApi(tenantCode: string, siteCode: string) {
  const ctx = { tenantCode, siteCode };

  return {
    // Status
    status: {
      get: () => tenantFetch<TenantStatus>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/status`,
        ctx
      ),
    },

    // Imports/Stops
    imports: {
      list: () => tenantFetch<StopImportJob[]>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports`,
        ctx
      ),
      get: (importId: string) => tenantFetch<StopImportJob>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports/${importId}`,
        ctx
      ),
      upload: (file: { filename: string; content: string }) => tenantFetch<StopImportJob>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports`,
        {
          ...ctx,
          method: 'POST',
          body: file,
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'upload-import', file.filename),
        }
      ),
      validate: (importId: string) => tenantFetch<StopImportJob>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports/${importId}/validate`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'validate-import', importId),
        }
      ),
      accept: (importId: string) => tenantFetch<StopImportJob>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports/${importId}/accept`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'accept-import', importId),
        }
      ),
      reject: (importId: string, reason: string) => tenantFetch<void>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/imports/${importId}/reject`,
        {
          ...ctx,
          method: 'POST',
          body: { reason },
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'reject-import', importId),
        }
      ),
    },

    // Teams Daily (with import/validate/publish flow)
    teams: {
      listDaily: (date: string) => tenantFetch<TeamDailyAssignment[]>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily?date=${date}`,
        ctx
      ),
      updateDaily: (assignmentId: string, data: { driver_2_id?: string | null; vehicle_id?: string }) => tenantFetch<TeamDailyAssignment>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/${assignmentId}`,
        {
          ...ctx,
          method: 'PATCH',
          body: data,
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'update-team-daily', assignmentId),
        }
      ),
      checkTwoPersonCompliance: (date: string) => tenantFetch<{
        compliant: boolean;
        violations: Array<{ stop_id: string; team_id: string; reason: string }>;
      }>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/check-two-person?date=${date}`,
        ctx
      ),
      // Import/Validate/Publish flow with 2-person hard gate
      import: (data: { date: string; filename: string; content_base64: string; content_sha256: string }) => tenantFetch<{
        import_id: string;
        date: string;
        filename: string;
        status: string;
        row_count: number;
        created_at: string;
      }>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/import`,
        {
          ...ctx,
          method: 'POST',
          body: data,
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'import-teams-daily', data.date, data.filename),
        }
      ),
      validate: (importId: string) => tenantFetch<{
        import_id: string;
        status: string;
        can_publish: boolean;
        blocking_reasons: string[];
        two_person_checks: Array<{
          team_code: string;
          demand_status: 'MATCHED' | 'MISMATCH_UNDER' | 'MISMATCH_OVER';
          team_size: number;
          required_size: number;
        }>;
      }>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/${importId}/validate`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'validate-teams-daily', importId),
        }
      ),
      // Publish - HARD GATE for UNDER + OVER violations
      publish: (importId: string) => tenantFetch<{
        import_id: string;
        publish_id: string;
        status: string;
        published_at: string;
        published_by: string;
        snapshot_hash: string;
      }>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/${importId}/publish`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'publish-teams-daily', importId),
        }
      ),
    },

    // Scenarios
    scenarios: {
      list: () => tenantFetch<RoutingScenario[]>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios`,
        ctx
      ),
      get: (scenarioId: string) => tenantFetch<RoutingScenario>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios/${scenarioId}`,
        ctx
      ),
      create: (data: { vertical: 'MEDIAMARKT' | 'HDL_PLUS'; plan_date: string }) => tenantFetch<RoutingScenario>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios`,
        {
          ...ctx,
          method: 'POST',
          body: data,
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'create-scenario', data.plan_date, data.vertical),
        }
      ),
      solve: (scenarioId: string, config?: { seed?: number; time_limit_seconds?: number }) => tenantFetch<RoutingPlan>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/scenarios/${scenarioId}/solve`,
        {
          ...ctx,
          method: 'POST',
          body: config || {},
          idempotencyKey: generateTenantIdempotencyKey(
            tenantCode, siteCode, 'solve-scenario', scenarioId,
            config?.seed?.toString() || 'default'
          ),
        }
      ),
    },

    // Plans
    plans: {
      get: (planId: string) => tenantFetch<RoutingPlan>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}`,
        ctx
      ),
      getAudit: (planId: string) => tenantFetch<AuditResult[]>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/audit`,
        ctx
      ),
      runAudit: (planId: string) => tenantFetch<AuditResult[]>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/audit`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'run-audit', planId),
        }
      ),
      lock: (planId: string) => tenantFetch<RoutingPlan>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/lock`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'lock-plan', planId),
        }
      ),
      // Freeze operations (separate from Lock)
      getFreeze: (planId: string) => tenantFetch<{
        plan_id: string;
        total_stops: number;
        frozen_stops: number;
        unfrozen_stops: number;
        freeze_status: 'NONE' | 'PARTIAL' | 'FULL';
        frozen_stop_ids: string[];
      }>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/freeze`,
        ctx
      ),
      freeze: (planId: string, data: { stop_ids: string[]; reason: string }) => tenantFetch<{
        plan_id: string;
        frozen_count: number;
        frozen_stop_ids: string[];
      }>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/freeze`,
        {
          ...ctx,
          method: 'POST',
          body: data,
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'freeze-stops', planId, ...data.stop_ids),
        }
      ),
      getEvidence: (planId: string) => tenantFetch<EvidencePack>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/evidence`,
        ctx
      ),
      generateEvidence: (planId: string) => tenantFetch<EvidencePack>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/evidence`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'generate-evidence', planId),
        }
      ),
    },

    // Repair
    repair: {
      listEvents: (planId: string) => tenantFetch<RepairEvent[]>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/repair`,
        ctx
      ),
      createEvent: (planId: string, data: { event_type: RepairEvent['event_type']; affected_stop_ids: string[] }) => tenantFetch<RepairEvent>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/repair`,
        {
          ...ctx,
          method: 'POST',
          body: data,
          idempotencyKey: generateTenantIdempotencyKey(
            tenantCode, siteCode, 'create-repair', planId, data.event_type, ...data.affected_stop_ids
          ),
        }
      ),
      executeRepair: (planId: string, eventId: string) => tenantFetch<RoutingPlan>(
        `/api/v1/tenants/${tenantCode}/sites/${siteCode}/plans/${planId}/repair/${eventId}/execute`,
        {
          ...ctx,
          method: 'POST',
          idempotencyKey: generateTenantIdempotencyKey(tenantCode, siteCode, 'execute-repair', planId, eventId),
        }
      ),
    },
  };
}
