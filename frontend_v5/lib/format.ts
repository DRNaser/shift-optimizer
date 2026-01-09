// =============================================================================
// SOLVEREIGN V4.3 - Formatting Utilities
// =============================================================================
// Shared formatting functions for Portal UI (German locale).
// =============================================================================

import type { DashboardStatusFilter, AckStatus } from "./portal-types";

// =============================================================================
// DATE/TIME FORMATTING
// =============================================================================

/**
 * Format date as German locale (DD.MM.YYYY).
 */
export function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return "-";
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("de-AT", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return dateString;
  }
}

/**
 * Format date with time (DD.MM.YYYY HH:mm).
 */
export function formatDateTime(dateString: string | null | undefined): string {
  if (!dateString) return "-";
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("de-AT", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateString;
  }
}

/**
 * Format time only (HH:mm).
 */
export function formatTime(timeString: string | null | undefined): string {
  if (!timeString) return "-";
  // If already in HH:mm format, return as is
  if (/^\d{2}:\d{2}$/.test(timeString)) {
    return timeString;
  }
  try {
    const date = new Date(timeString);
    return date.toLocaleTimeString("de-AT", {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return timeString;
  }
}

/**
 * Format relative time (e.g., "vor 2 Stunden").
 */
export function formatRelativeTime(dateString: string | null | undefined): string {
  if (!dateString) return "-";
  try {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMin / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMin < 1) return "gerade eben";
    if (diffMin < 60) return `vor ${diffMin} Min.`;
    if (diffHours < 24) return `vor ${diffHours} Std.`;
    if (diffDays < 7) return `vor ${diffDays} Tag${diffDays > 1 ? "en" : ""}`;
    return formatDate(dateString);
  } catch {
    return dateString;
  }
}

/**
 * Format week range (DD.MM. - DD.MM.YYYY).
 */
export function formatWeekRange(
  weekStart: string | null | undefined,
  weekEnd: string | null | undefined
): string {
  if (!weekStart) return "-";
  try {
    const start = new Date(weekStart);
    const end = weekEnd ? new Date(weekEnd) : null;

    const startStr = start.toLocaleDateString("de-AT", {
      day: "2-digit",
      month: "2-digit",
    });

    if (!end) return startStr;

    const endStr = end.toLocaleDateString("de-AT", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });

    return `${startStr} - ${endStr}`;
  } catch {
    return weekStart;
  }
}

/**
 * Format day of week in German.
 */
export function formatDayOfWeek(day: string | null | undefined): string {
  if (!day) return "-";
  const days: Record<string, string> = {
    Monday: "Montag",
    Tuesday: "Dienstag",
    Wednesday: "Mittwoch",
    Thursday: "Donnerstag",
    Friday: "Freitag",
    Saturday: "Samstag",
    Sunday: "Sonntag",
    Mon: "Mo",
    Tue: "Di",
    Wed: "Mi",
    Thu: "Do",
    Fri: "Fr",
    Sat: "Sa",
    Sun: "So",
  };
  return days[day] || day;
}

// =============================================================================
// NUMBER FORMATTING
// =============================================================================

/**
 * Format hours (e.g., 42.5 -> "42,5 Std.").
 */
export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "-";
  return `${hours.toLocaleString("de-AT", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} Std.`;
}

/**
 * Format percentage (e.g., 0.85 -> "85%", or 85 -> "85%").
 */
export function formatPercent(
  value: number | null | undefined,
  decimals: number = 0
): string {
  if (value === null || value === undefined) return "-";
  // If value is < 1, assume it's a decimal (0.85 = 85%)
  const pct = value < 1 && value > 0 ? value * 100 : value;
  return `${pct.toFixed(decimals)}%`;
}

/**
 * Format count with optional suffix.
 */
export function formatCount(
  count: number | null | undefined,
  suffix?: string
): string {
  if (count === null || count === undefined) return "-";
  const formatted = count.toLocaleString("de-AT");
  return suffix ? `${formatted} ${suffix}` : formatted;
}

// =============================================================================
// STATUS FORMATTING
// =============================================================================

/**
 * Get German label for dashboard filter.
 */
export function getFilterLabel(filter: DashboardStatusFilter): string {
  const labels: Record<DashboardStatusFilter, string> = {
    ALL: "Alle",
    UNREAD: "Ungelesen",
    UNACKED: "Nicht bestätigt",
    ACCEPTED: "Akzeptiert",
    DECLINED: "Abgelehnt",
    SKIPPED: "Übersprungen",
    FAILED: "Fehlgeschlagen",
  };
  return labels[filter] || filter;
}

/**
 * Get German label for ack status.
 */
export function getAckStatusLabel(status: AckStatus | null | undefined): string {
  if (!status) return "Ausstehend";
  const labels: Record<AckStatus, string> = {
    PENDING: "Ausstehend",
    ACCEPTED: "Akzeptiert",
    DECLINED: "Abgelehnt",
  };
  return labels[status] || status;
}

/**
 * Get German label for overall driver status.
 */
export function getOverallStatusLabel(status: string | null | undefined): string {
  if (!status) return "-";
  const labels: Record<string, string> = {
    NOT_ISSUED: "Nicht gesendet",
    PENDING: "Gesendet",
    DELIVERED: "Zugestellt",
    READ: "Gelesen",
    ACCEPTED: "Akzeptiert",
    DECLINED: "Abgelehnt",
    SKIPPED: "Übersprungen",
    FAILED: "Fehlgeschlagen",
    EXPIRED: "Abgelaufen",
    REVOKED: "Widerrufen",
  };
  return labels[status] || status;
}

/**
 * Get color class for status badge.
 */
export function getStatusColor(status: string | null | undefined): string {
  if (!status) return "bg-slate-500/20 text-slate-400";
  const colors: Record<string, string> = {
    NOT_ISSUED: "bg-slate-500/20 text-slate-400",
    PENDING: "bg-blue-500/20 text-blue-400",
    DELIVERED: "bg-cyan-500/20 text-cyan-400",
    READ: "bg-purple-500/20 text-purple-400",
    ACCEPTED: "bg-emerald-500/20 text-emerald-400",
    DECLINED: "bg-amber-500/20 text-amber-400",
    SKIPPED: "bg-orange-500/20 text-orange-400",
    FAILED: "bg-red-500/20 text-red-400",
    EXPIRED: "bg-gray-500/20 text-gray-400",
    REVOKED: "bg-rose-500/20 text-rose-400",
  };
  return colors[status] || "bg-slate-500/20 text-slate-400";
}

/**
 * Get color class for ack status.
 */
export function getAckStatusColor(status: AckStatus | null | undefined): string {
  if (!status || status === "PENDING") return "bg-blue-500/20 text-blue-400";
  if (status === "ACCEPTED") return "bg-emerald-500/20 text-emerald-400";
  if (status === "DECLINED") return "bg-amber-500/20 text-amber-400";
  return "bg-slate-500/20 text-slate-400";
}

// =============================================================================
// DELIVERY CHANNEL FORMATTING
// =============================================================================

/**
 * Get label for delivery channel.
 */
export function getChannelLabel(channel: string | null | undefined): string {
  if (!channel) return "-";
  const labels: Record<string, string> = {
    EMAIL: "E-Mail",
    WHATSAPP: "WhatsApp",
    SMS: "SMS",
  };
  return labels[channel] || channel;
}

/**
 * Get icon name for delivery channel (for lucide-react).
 */
export function getChannelIcon(channel: string | null | undefined): string {
  if (!channel) return "Mail";
  const icons: Record<string, string> = {
    EMAIL: "Mail",
    WHATSAPP: "MessageCircle",
    SMS: "Smartphone",
  };
  return icons[channel] || "Mail";
}

// =============================================================================
// DECLINE REASON FORMATTING
// =============================================================================

/**
 * Get German label for decline reason code.
 */
export function getDeclineReasonLabel(code: string | null | undefined): string {
  if (!code) return "-";
  const labels: Record<string, string> = {
    PERSONAL: "Persönliche Gründe",
    MEDICAL: "Medizinische Gründe",
    CONFLICT: "Terminkonflikt",
    OTHER: "Sonstiges",
  };
  return labels[code] || code;
}

/**
 * Get German label for skip reason code.
 */
export function getSkippedReasonLabel(code: string | null | undefined): string {
  if (!code) return "-";
  const labels: Record<string, string> = {
    NO_CONTACT: "Keine Kontaktdaten",
    NO_SHIFTS: "Keine Schichten",
    NO_CHANNEL: "Kein Zustellkanal",
    OPT_OUT: "Abgemeldet",
    DUPLICATE: "Duplikat",
    EXCLUDED: "Ausgeschlossen",
    MANUAL: "Manuell übersprungen",
    SYSTEM: "Systembedingt",
  };
  return labels[code] || code;
}
