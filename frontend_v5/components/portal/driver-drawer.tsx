"use client";

import { X, Mail, MessageCircle, Smartphone, Clock, Eye, Check, XCircle } from "lucide-react";
import type { DriverStatus } from "@/lib/portal-types";
import {
  formatDateTime,
  formatHours,
  getOverallStatusLabel,
  getStatusColor,
  getAckStatusLabel,
  getAckStatusColor,
  getChannelLabel,
  getDeclineReasonLabel,
  getSkippedReasonLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

interface DriverDrawerProps {
  driver: DriverStatus | null;
  isOpen: boolean;
  onClose: () => void;
  onResend?: (driverId: string) => void;
}

function ChannelIcon({ channel }: { channel: string | null }) {
  if (!channel) return <Mail className="w-5 h-5 text-slate-500" />;
  switch (channel) {
    case "EMAIL":
      return <Mail className="w-5 h-5 text-slate-400" />;
    case "WHATSAPP":
      return <MessageCircle className="w-5 h-5 text-emerald-400" />;
    case "SMS":
      return <Smartphone className="w-5 h-5 text-blue-400" />;
    default:
      return <Mail className="w-5 h-5 text-slate-500" />;
  }
}

function TimelineItem({
  icon: Icon,
  label,
  time,
  isActive,
  color,
}: {
  icon: React.ElementType;
  label: string;
  time: string | null;
  isActive: boolean;
  color: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div
        className={cn(
          "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
          isActive ? color : "bg-slate-700/50"
        )}
      >
        <Icon className={cn("w-4 h-4", isActive ? "text-white" : "text-slate-500")} />
      </div>
      <div className="flex-1 min-w-0">
        <p className={cn("text-sm font-medium", isActive ? "text-white" : "text-slate-500")}>
          {label}
        </p>
        <p className="text-xs text-slate-500">{time ? formatDateTime(time) : "Ausstehend"}</p>
      </div>
    </div>
  );
}

export function DriverDrawer({ driver, isOpen, onClose, onResend }: DriverDrawerProps) {
  if (!isOpen || !driver) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 bottom-0 w-full max-w-md bg-slate-900 border-l border-slate-800 z-50 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-slate-900 border-b border-slate-800 px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">{driver.driver_name}</h2>
              <p className="text-sm text-slate-500">{driver.driver_id}</p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-slate-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5 text-slate-400" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Status Badge */}
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "inline-flex items-center px-3 py-1.5 rounded-full text-sm font-medium",
                getStatusColor(driver.overall_status)
              )}
            >
              {getOverallStatusLabel(driver.overall_status)}
            </span>
            {driver.ack_status && (
              <span
                className={cn(
                  "inline-flex items-center px-3 py-1.5 rounded-full text-sm font-medium",
                  getAckStatusColor(driver.ack_status)
                )}
              >
                {getAckStatusLabel(driver.ack_status)}
              </span>
            )}
          </div>

          {/* Delivery Info */}
          <div className="bg-slate-800/50 rounded-lg p-4 space-y-3">
            <h3 className="text-sm font-medium text-slate-400">Zustellung</h3>
            <div className="flex items-center gap-3">
              <ChannelIcon channel={driver.delivery_channel} />
              <span className="text-white">{getChannelLabel(driver.delivery_channel)}</span>
            </div>
            {driver.error_message && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                <p className="text-sm text-red-400">{driver.error_message}</p>
              </div>
            )}
            {driver.skip_reason && (
              <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-3">
                <p className="text-sm font-medium text-orange-400">Übersprungen</p>
                <p className="text-sm text-orange-300 mt-1">{getSkippedReasonLabel(driver.skip_reason)}</p>
              </div>
            )}
          </div>

          {/* Timeline */}
          <div className="bg-slate-800/50 rounded-lg p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-4">Verlauf</h3>
            <div className="space-y-4">
              <TimelineItem
                icon={Mail}
                label="Gesendet"
                time={driver.issued_at}
                isActive={!!driver.issued_at}
                color="bg-blue-500"
              />
              <TimelineItem
                icon={Check}
                label="Zugestellt"
                time={driver.delivered_at}
                isActive={!!driver.delivered_at}
                color="bg-cyan-500"
              />
              <TimelineItem
                icon={Eye}
                label="Gelesen"
                time={driver.read_at}
                isActive={!!driver.read_at}
                color="bg-purple-500"
              />
              <TimelineItem
                icon={driver.ack_status === "ACCEPTED" ? Check : XCircle}
                label={driver.ack_status === "ACCEPTED" ? "Akzeptiert" : driver.ack_status === "DECLINED" ? "Abgelehnt" : "Bestätigung"}
                time={driver.acked_at}
                isActive={!!driver.acked_at}
                color={driver.ack_status === "ACCEPTED" ? "bg-emerald-500" : driver.ack_status === "DECLINED" ? "bg-amber-500" : "bg-slate-500"}
              />
            </div>
          </div>

          {/* Decline Details */}
          {driver.ack_status === "DECLINED" && (
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4">
              <h3 className="text-sm font-medium text-amber-400 mb-2">Ablehnungsgrund</h3>
              <p className="text-white">{getDeclineReasonLabel(driver.decline_reason_code)}</p>
              {driver.decline_free_text && (
                <p className="text-sm text-slate-400 mt-2">{driver.decline_free_text}</p>
              )}
            </div>
          )}

          {/* Shift Info */}
          <div className="bg-slate-800/50 rounded-lg p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3">Schichtinfo</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-slate-500">Schichten</p>
                <p className="text-lg font-semibold text-white">{driver.shift_count}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Stunden</p>
                <p className="text-lg font-semibold text-emerald-400">
                  {formatHours(driver.total_hours)}
                </p>
              </div>
            </div>
          </div>

          {/* Actions */}
          {onResend && (driver.overall_status === "FAILED" || driver.overall_status === "NOT_ISSUED") && (
            <button
              onClick={() => onResend(driver.driver_id)}
              className="w-full px-4 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors"
            >
              Erneut senden
            </button>
          )}
        </div>
      </div>
    </>
  );
}
