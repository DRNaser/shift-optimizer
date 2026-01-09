// =============================================================================
// SOLVEREIGN V4.3 - Portal API Client
// =============================================================================
// API client for Driver Portal + Dispatcher Dashboard.
//
// SECURITY NOTES:
// 1. Token is exchanged for HttpOnly session cookie on first load
// 2. All subsequent calls use session cookie (refresh-safe)
// 3. Token is stripped from URL after exchange
// 4. Error responses never expose internal details
// 5. Admin endpoints require Entra ID auth (via BFF)
// =============================================================================

import type {
  PortalState,
  PortalViewResponse,
  DashboardSummaryResponse,
  DashboardDetailsResponse,
  DashboardStatusFilter,
  ResendRequest,
  ResendResult,
  DriverStatus,
} from "./portal-types";

// =============================================================================
// SESSION-BASED PORTAL API (Token Exchange Pattern)
// =============================================================================

/**
 * Exchange token for session cookie and get plan.
 * Called once on initial page load with token from URL.
 * After this, token is stripped from URL and session cookie is used.
 */
export async function exchangeTokenForSession(token: string): Promise<PortalState> {
  try {
    const response = await fetch("/api/portal/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
      credentials: "include", // Include cookies
    });

    const data = await response.json();

    if (!data.ok) {
      if (data.status === "expired") {
        return { status: "expired", errorMessage: "Dieser Link ist abgelaufen." };
      }
      if (data.status === "superseded") {
        return {
          status: "superseded",
          supersededBy: data.new_snapshot_id,
          errorMessage: "Eine neue Version des Plans ist verfügbar.",
        };
      }
      return { status: "error", errorMessage: data.error || "Ungültiger Link" };
    }

    return {
      status: "valid",
      plan: data.plan,
      ackStatus: data.ack_status || "PENDING",
    };
  } catch {
    return { status: "error", errorMessage: "Verbindungsfehler" };
  }
}

/**
 * Check existing session and get plan (for refresh/back).
 * Uses HttpOnly session cookie - no token needed.
 */
export async function getSessionPlan(): Promise<PortalState> {
  try {
    const response = await fetch("/api/portal/session", {
      method: "GET",
      cache: "no-store",
      credentials: "include",
    });

    const data = await response.json();

    if (!data.ok) {
      if (data.status === "no_session") {
        return { status: "error", errorMessage: "no_session" }; // Special marker
      }
      if (data.status === "expired") {
        return { status: "expired", errorMessage: "Ihre Sitzung ist abgelaufen." };
      }
      if (data.status === "superseded") {
        return {
          status: "superseded",
          supersededBy: data.new_snapshot_id,
          errorMessage: "Eine neue Version des Plans ist verfügbar.",
        };
      }
      return { status: "error", errorMessage: data.error || "Fehler beim Laden" };
    }

    return {
      status: "valid",
      plan: data.plan,
      ackStatus: data.ack_status || "PENDING",
    };
  } catch {
    return { status: "error", errorMessage: "Verbindungsfehler" };
  }
}

/**
 * Record read receipt using session cookie.
 * Silent failure - doesn't affect user experience.
 */
export async function recordReadReceiptSession(): Promise<void> {
  try {
    await fetch("/api/portal/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
      cache: "no-store",
      credentials: "include",
    });
  } catch {
    // Silently fail - read tracking is not critical
  }
}

/**
 * Submit acknowledgment using session cookie.
 */
export async function submitAcknowledgmentSession(
  status: "ACCEPTED" | "DECLINED",
  reasonCode?: string,
  freeText?: string
): Promise<{ success: boolean; error?: string }> {
  try {
    const response = await fetch("/api/portal/ack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        reason_code: reasonCode,
        free_text: freeText,
      }),
      cache: "no-store",
      credentials: "include",
    });

    if (!response.ok) {
      const data = await response.json();
      return { success: false, error: data.detail || "Fehler beim Bestätigen" };
    }

    return { success: true };
  } catch {
    return { success: false, error: "Verbindungsfehler" };
  }
}

// =============================================================================
// LEGACY TOKEN-BASED API (kept for backwards compatibility)
// =============================================================================

/**
 * @deprecated Use exchangeTokenForSession instead
 */
export async function validatePortalToken(token: string): Promise<PortalState> {
  return exchangeTokenForSession(token);
}

/**
 * @deprecated Use recordReadReceiptSession instead
 */
export async function recordReadReceipt(token: string): Promise<void> {
  return recordReadReceiptSession();
}

/**
 * @deprecated Use submitAcknowledgmentSession instead
 */
export async function submitAcknowledgment(
  token: string,
  status: "ACCEPTED" | "DECLINED",
  reasonCode?: string,
  freeText?: string
): Promise<{ success: boolean; error?: string }> {
  return submitAcknowledgmentSession(status, reasonCode, freeText);
}

// =============================================================================
// DISPATCHER DASHBOARD API (Entra ID Auth Required via BFF)
// =============================================================================

/**
 * Fetch dashboard summary for a snapshot.
 * Called from BFF route, not directly from client.
 */
export async function fetchDashboardSummary(
  snapshotId: string
): Promise<DashboardSummaryResponse | { error: string }> {
  try {
    const response = await fetch(
      `/api/portal-admin/summary?snapshot_id=${snapshotId}`,
      { cache: "no-store" }
    );

    if (!response.ok) {
      const data = await response.json();
      return { error: data.error || "Fehler beim Laden der Zusammenfassung" };
    }

    return await response.json();
  } catch {
    return { error: "Verbindungsfehler" };
  }
}

/**
 * Fetch driver list with optional filters.
 */
export async function fetchDriverList(
  snapshotId: string,
  filter: DashboardStatusFilter = "ALL",
  page: number = 1,
  pageSize: number = 50
): Promise<DashboardDetailsResponse | { error: string }> {
  try {
    const params = new URLSearchParams({
      snapshot_id: snapshotId,
      filter,
      page: page.toString(),
      page_size: pageSize.toString(),
    });

    const response = await fetch(`/api/portal-admin/details?${params}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      const data = await response.json();
      return { error: data.error || "Fehler beim Laden der Fahrerliste" };
    }

    return await response.json();
  } catch {
    return { error: "Verbindungsfehler" };
  }
}

/**
 * Trigger resend for selected drivers or filter.
 */
export async function triggerResend(
  request: ResendRequest
): Promise<ResendResult> {
  try {
    const response = await fetch("/api/portal-admin/resend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      cache: "no-store",
    });

    if (!response.ok) {
      const data = await response.json();
      return {
        success: false,
        queued_count: 0,
        skipped_count: 0,
        error: data.error || "Fehler beim Erneut Senden",
      };
    }

    return await response.json();
  } catch {
    return {
      success: false,
      queued_count: 0,
      skipped_count: 0,
      error: "Verbindungsfehler",
    };
  }
}

/**
 * Export driver list as CSV.
 */
export async function exportDriversCsv(
  snapshotId: string,
  filter: DashboardStatusFilter = "ALL"
): Promise<Blob | { error: string }> {
  try {
    const params = new URLSearchParams({
      snapshot_id: snapshotId,
      filter,
      format: "csv",
    });

    const response = await fetch(`/api/portal-admin/export?${params}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      const data = await response.json();
      return { error: data.error || "Fehler beim Export" };
    }

    return await response.blob();
  } catch {
    return { error: "Verbindungsfehler" };
  }
}

/**
 * Get list of available snapshots for the current site.
 */
export async function fetchSnapshots(): Promise<
  { snapshots: Array<{ id: string; week_start: string; created_at: string }> } | { error: string }
> {
  try {
    const response = await fetch("/api/portal-admin/snapshots", {
      cache: "no-store",
    });

    if (!response.ok) {
      const data = await response.json();
      return { error: data.error || "Fehler beim Laden der Snapshots" };
    }

    return await response.json();
  } catch {
    return { error: "Verbindungsfehler" };
  }
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Calculate KPIs from driver list.
 */
export function calculateKPIs(drivers: DriverStatus[]): {
  total: number;
  issued: number;
  delivered: number;
  read: number;
  accepted: number;
  declined: number;
  skipped: number;
  failed: number;
  deliveryRate: number;
  readRate: number;
  ackRate: number;
} {
  const total = drivers.length;
  const issued = drivers.filter((d) => d.issued_at).length;
  const delivered = drivers.filter((d) => d.delivered_at).length;
  const read = drivers.filter((d) => d.read_at).length;
  const accepted = drivers.filter((d) => d.ack_status === "ACCEPTED").length;
  const declined = drivers.filter((d) => d.ack_status === "DECLINED").length;
  const skipped = drivers.filter((d) => d.overall_status === "SKIPPED").length;
  const failed = drivers.filter((d) => d.overall_status === "FAILED").length;

  // Exclude SKIPPED from denominators (send-attemptable basis)
  const sendAttemptable = total - skipped;
  const deliveryRate =
    sendAttemptable > 0 ? (delivered / sendAttemptable) * 100 : 0;
  const readRate = delivered > 0 ? (read / delivered) * 100 : 0;
  const ackRate =
    read > 0 ? ((accepted + declined) / read) * 100 : 0;

  return {
    total,
    issued,
    delivered,
    read,
    accepted,
    declined,
    skipped,
    failed,
    deliveryRate,
    readRate,
    ackRate,
  };
}

/**
 * Filter drivers by status.
 */
export function filterDrivers(
  drivers: DriverStatus[],
  filter: DashboardStatusFilter
): DriverStatus[] {
  switch (filter) {
    case "UNREAD":
      return drivers.filter((d) => d.delivered_at && !d.read_at);
    case "UNACKED":
      return drivers.filter((d) => d.read_at && !d.ack_status);
    case "ACCEPTED":
      return drivers.filter((d) => d.ack_status === "ACCEPTED");
    case "DECLINED":
      return drivers.filter((d) => d.ack_status === "DECLINED");
    case "SKIPPED":
      return drivers.filter((d) => d.overall_status === "SKIPPED");
    case "FAILED":
      return drivers.filter((d) => d.overall_status === "FAILED");
    case "ALL":
    default:
      return drivers;
  }
}
