"use client";

import { useState } from "react";
import { X, Loader2, AlertTriangle } from "lucide-react";
import type { DashboardStatusFilter, ResendResult } from "@/lib/portal-types";
import { getFilterLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ResendDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (reason?: string) => Promise<ResendResult>;
  filter: DashboardStatusFilter;
  selectedCount: number;
  isFilterMode: boolean; // true = resend by filter, false = resend selected drivers
}

export function ResendDialog({
  isOpen,
  onClose,
  onConfirm,
  filter,
  selectedCount,
  isFilterMode,
}: ResendDialogProps) {
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<ResendResult | null>(null);

  // Determine if reason is required (DECLINED or SKIPPED filter)
  const requiresReason = filter === "DECLINED" || filter === "SKIPPED";
  const canSubmit = !requiresReason || reason.length >= 10;

  const handleSubmit = async () => {
    if (!canSubmit) return;

    setIsSubmitting(true);
    setResult(null);

    try {
      const res = await onConfirm(requiresReason ? reason : undefined);
      setResult(res);
      if (res.success) {
        // Auto-close after success
        setTimeout(() => {
          onClose();
          setResult(null);
          setReason("");
        }, 2000);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      onClose();
      setResult(null);
      setReason("");
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/70 z-50" onClick={handleClose} />

      {/* Dialog */}
      <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
        <div className="bg-slate-800 rounded-xl w-full max-w-md border border-slate-700 shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
            <h2 className="text-lg font-semibold text-white">Erneut senden</h2>
            <button
              onClick={handleClose}
              disabled={isSubmitting}
              className="p-2 hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50"
            >
              <X className="w-5 h-5 text-slate-400" />
            </button>
          </div>

          {/* Content */}
          <div className="px-6 py-4 space-y-4">
            {/* Summary */}
            <div className="bg-slate-900 rounded-lg p-4">
              <p className="text-sm text-slate-400">
                {isFilterMode ? (
                  <>
                    Alle Fahrer mit Status{" "}
                    <span className="font-medium text-white">
                      {getFilterLabel(filter)}
                    </span>{" "}
                    werden erneut benachrichtigt.
                  </>
                ) : (
                  <>
                    <span className="font-medium text-white">{selectedCount}</span>{" "}
                    ausgewählte Fahrer werden erneut benachrichtigt.
                  </>
                )}
              </p>
            </div>

            {/* Warning for DECLINED/SKIPPED */}
            {requiresReason && (
              <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-amber-400">
                      {filter === "DECLINED"
                        ? "Vorsicht: Fahrer haben bereits abgelehnt"
                        : "Vorsicht: Fahrer wurden übersprungen (DNC)"}
                    </p>
                    <p className="text-xs text-amber-400/70 mt-1">
                      Ein Grund mit mindestens 10 Zeichen ist erforderlich.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Reason Input */}
            {requiresReason && (
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Begründung *
                </label>
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Warum werden diese Fahrer erneut kontaktiert?"
                  className={cn(
                    "w-full px-4 py-3 bg-slate-900 border rounded-lg text-white placeholder-slate-500 focus:outline-none resize-none",
                    reason.length > 0 && reason.length < 10
                      ? "border-red-500 focus:border-red-500"
                      : "border-slate-700 focus:border-blue-500"
                  )}
                  rows={3}
                  disabled={isSubmitting}
                />
                <p className="text-xs text-slate-500 mt-1">
                  {reason.length}/10 Zeichen (Minimum)
                </p>
              </div>
            )}

            {/* Result Message */}
            {result && (
              <div
                className={cn(
                  "rounded-lg p-4",
                  result.success
                    ? "bg-emerald-500/10 border border-emerald-500/30"
                    : "bg-red-500/10 border border-red-500/30"
                )}
              >
                {result.success ? (
                  <p className="text-sm text-emerald-400">
                    {result.queued_count} Nachrichten wurden in die Warteschlange gestellt.
                    {result.skipped_count > 0 && (
                      <span className="block text-xs text-emerald-400/70 mt-1">
                        {result.skipped_count} wurden übersprungen (bereits gesendet oder DNC).
                      </span>
                    )}
                  </p>
                ) : (
                  <p className="text-sm text-red-400">{result.error}</p>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex gap-3 px-6 py-4 border-t border-slate-700">
            <button
              onClick={handleClose}
              disabled={isSubmitting}
              className="flex-1 px-4 py-3 bg-slate-700 hover:bg-slate-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50"
            >
              Abbrechen
            </button>
            <button
              onClick={handleSubmit}
              disabled={!canSubmit || isSubmitting}
              className="flex-1 px-4 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Wird gesendet...
                </>
              ) : (
                "Bestätigen"
              )}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
