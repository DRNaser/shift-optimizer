// =============================================================================
// SOLVEREIGN V4.3 - Portal Types
// =============================================================================
// Shared types for Driver Portal + Dispatcher Dashboard.
// SECURITY: No token types exposed - tokens are URL params only, never stored.
// =============================================================================

// =============================================================================
// DRIVER PORTAL TYPES
// =============================================================================

export interface Shift {
  date: string;
  day_of_week: string;
  start_time: string;
  end_time: string;
  tour_id?: string;
  route_name?: string;
  hours: number;
}

export interface DriverPlan {
  driver_id: string;
  driver_name: string;
  week_start: string;
  week_end: string;
  shifts: Shift[];
  total_hours: number;
  message?: string;
}

export type PortalStatus =
  | "loading"
  | "valid"
  | "expired"
  | "revoked"
  | "error"
  | "superseded";

export type AckStatus = "PENDING" | "ACCEPTED" | "DECLINED";

export interface PortalState {
  status: PortalStatus;
  plan?: DriverPlan;
  ackStatus?: AckStatus;
  supersededBy?: string;
  errorMessage?: string;
}

export interface DeclineReason {
  code: string;
  label: string;
}

export const DECLINE_REASONS: DeclineReason[] = [
  { code: "PERSONAL", label: "Persönliche Gründe" },
  { code: "MEDICAL", label: "Medizinische Gründe" },
  { code: "CONFLICT", label: "Terminkonflikt" },
  { code: "OTHER", label: "Sonstiges" },
];

// =============================================================================
// DISPATCHER DASHBOARD TYPES
// =============================================================================

export type DashboardStatusFilter =
  | "ALL"
  | "UNREAD"
  | "UNACKED"
  | "ACCEPTED"
  | "DECLINED"
  | "SKIPPED"
  | "FAILED";

export interface SnapshotSummary {
  snapshot_id: string;
  week_start: string;
  week_end: string;
  total_count: number;
  issued_count: number;
  read_count: number;
  accepted_count: number;
  declined_count: number;
  skipped_count: number;
  failed_count: number;
  delivery_rate: number;
  read_rate: number;
  ack_rate: number;
  send_attemptable_count: number;
  first_issued_at?: string;
  last_activity_at?: string;
}

export interface DriverStatus {
  driver_id: string;
  driver_name: string;
  overall_status:
    | "NOT_ISSUED"
    | "PENDING"
    | "DELIVERED"
    | "READ"
    | "ACCEPTED"
    | "DECLINED"
    | "SKIPPED"
    | "FAILED"
    | "EXPIRED"
    | "REVOKED";
  delivery_channel: "EMAIL" | "WHATSAPP" | "SMS" | null;
  issued_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  acked_at: string | null;
  ack_status: AckStatus | null;
  decline_reason_code: string | null;
  decline_free_text: string | null;
  skip_reason: string | null;
  error_message: string | null;
  total_hours: number;
  shift_count: number;
}

export interface DashboardKPIs {
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
}

export interface ResendRequest {
  snapshot_id: string;
  filter: DashboardStatusFilter;
  driver_ids?: string[];
  include_declined?: boolean;
  declined_reason?: string;
  include_skipped?: boolean;
  skipped_reason?: string;
}

export interface ResendResult {
  success: boolean;
  queued_count: number;
  skipped_count: number;
  error?: string;
}

// =============================================================================
// API RESPONSE TYPES
// =============================================================================

export interface PortalViewResponse {
  plan: DriverPlan;
  ack_status: AckStatus;
}

export interface PortalAckRequest {
  token: string;
  status: "ACCEPTED" | "DECLINED";
  reason_code?: string;
  free_text?: string;
}

export interface DashboardSummaryResponse {
  summary: SnapshotSummary;
}

export interface DashboardDetailsResponse {
  drivers: DriverStatus[];
  total_count: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

// =============================================================================
// UI STATE TYPES
// =============================================================================

export interface PaginationState {
  page: number;
  pageSize: number;
  totalCount: number;
}

export interface SortState {
  field: keyof DriverStatus | null;
  direction: "asc" | "desc";
}

export interface DrawerState {
  isOpen: boolean;
  driver: DriverStatus | null;
}
