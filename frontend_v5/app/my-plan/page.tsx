"use client";

import { useState, useEffect, useCallback, Suspense, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { CheckCircle, XCircle, AlertTriangle, Clock, Calendar, Loader2 } from "lucide-react";

// =============================================================================
// SECURITY NOTES - V4.3 Hardened (Session Cookie Pattern)
// =============================================================================
// 1. Token is exchanged for HttpOnly session cookie on first load
// 2. Session cookie is used for all subsequent requests (refresh-safe)
// 3. Token is stripped from URL after successful exchange
// 4. Token is NEVER logged to console, analytics, or error tracking
// 5. Read receipt is debounced + idempotent (fires only once per session)
// 6. CSP: no external img-src, form-action restricted to 'self'
// 7. No external resources loaded (fonts via self-hosted or system fonts)
// =============================================================================

import type { PortalState, Shift, AckStatus } from "@/lib/portal-types";
import { DECLINE_REASONS } from "@/lib/portal-types";
import {
  exchangeTokenForSession,
  getSessionPlan,
  recordReadReceiptSession,
  submitAcknowledgmentSession,
} from "@/lib/portal-api";

// =============================================================================
// COMPONENTS
// =============================================================================

function LoadingState() {
  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center">
      <div className="text-center">
        <Loader2 className="w-12 h-12 text-blue-400 animate-spin mx-auto mb-4" />
        <p className="text-slate-400">Plan wird geladen...</p>
      </div>
    </div>
  );
}

function ErrorState({ message, showRetry = false }: { message: string; showRetry?: boolean }) {
  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="bg-slate-800 rounded-xl p-8 max-w-md text-center border border-slate-700">
        <AlertTriangle className="w-16 h-16 text-amber-400 mx-auto mb-4" />
        <h1 className="text-xl font-bold text-white mb-2">Link ungültig</h1>
        <p className="text-slate-400 mb-4">{message}</p>
        {showRetry && (
          <p className="text-sm text-slate-500">
            Bitte fordern Sie einen neuen Link bei der Disposition an.
          </p>
        )}
      </div>
    </div>
  );
}

function ExpiredState() {
  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="bg-slate-800 rounded-xl p-8 max-w-md text-center border border-amber-500/30">
        <Clock className="w-16 h-16 text-amber-400 mx-auto mb-4" />
        <h1 className="text-xl font-bold text-white mb-2">Link abgelaufen</h1>
        <p className="text-slate-400 mb-4">
          Dieser Link ist nicht mehr gültig.
        </p>
        <p className="text-sm text-slate-500">
          Bitte fordern Sie einen neuen Link bei der Disposition an.
        </p>
      </div>
    </div>
  );
}

function SupersededState({ newSnapshotMessage }: { newSnapshotMessage: string }) {
  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="bg-slate-800 rounded-xl p-8 max-w-md text-center border border-blue-500/30">
        <div className="w-16 h-16 bg-blue-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
          <Calendar className="w-8 h-8 text-blue-400" />
        </div>
        <h1 className="text-xl font-bold text-white mb-2">Neue Version verfügbar</h1>
        <p className="text-slate-400 mb-4">{newSnapshotMessage}</p>
        <p className="text-sm text-slate-500">
          Sie erhalten in Kürze einen neuen Link.
        </p>
      </div>
    </div>
  );
}

function ShiftCard({ shift }: { shift: Shift }) {
  return (
    <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700 hover:border-slate-600 transition-colors">
      <div className="flex justify-between items-start mb-2">
        <div>
          <p className="text-sm font-medium text-slate-400">{shift.day_of_week}</p>
          <p className="text-lg font-bold text-white">{shift.date}</p>
        </div>
        <div className="text-right">
          <p className="text-lg font-mono text-emerald-400">
            {shift.start_time} - {shift.end_time}
          </p>
          <p className="text-sm text-slate-500">{shift.hours.toFixed(1)} Std.</p>
        </div>
      </div>
      {shift.route_name && (
        <div className="mt-2 pt-2 border-t border-slate-700/50">
          <p className="text-sm text-slate-400">
            <span className="text-slate-500">Route:</span> {shift.route_name}
          </p>
        </div>
      )}
    </div>
  );
}

function DeclineModal({
  onConfirm,
  onCancel,
  isSubmitting,
}: {
  onConfirm: (reason: string, text: string) => void;
  onCancel: () => void;
  isSubmitting: boolean;
}) {
  const [reason, setReason] = useState("");
  const [freeText, setFreeText] = useState("");

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
      <div className="bg-slate-800 rounded-xl p-6 max-w-md w-full border border-slate-700">
        <h2 className="text-xl font-bold text-white mb-4">Plan ablehnen</h2>
        <p className="text-slate-400 mb-4">
          Bitte geben Sie einen Grund für die Ablehnung an:
        </p>

        <div className="space-y-2 mb-4">
          {DECLINE_REASONS.map((r) => (
            <button
              key={r.code}
              onClick={() => setReason(r.code)}
              className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                reason === r.code
                  ? "bg-amber-500/20 border-amber-500/50 text-amber-300"
                  : "bg-slate-700/50 border-slate-600 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>

        <textarea
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder="Zusätzliche Anmerkungen (optional)"
          className="w-full px-4 py-3 bg-slate-700/50 border border-slate-600 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 resize-none"
          rows={3}
        />

        <div className="flex gap-3 mt-6">
          <button
            onClick={onCancel}
            disabled={isSubmitting}
            className="flex-1 px-4 py-3 bg-slate-700 hover:bg-slate-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50"
          >
            Abbrechen
          </button>
          <button
            onClick={() => onConfirm(reason, freeText)}
            disabled={!reason || isSubmitting}
            className="flex-1 px-4 py-3 bg-amber-600 hover:bg-amber-500 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Wird gesendet...
              </>
            ) : (
              "Ablehnen"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function DriverPortalContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("t");

  const [state, setState] = useState<PortalState>({ status: "loading" });
  const [showDeclineModal, setShowDeclineModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Debounce ref: ensures read receipt only fires once per session
  const hasRecordedRead = useRef(false);
  const hasExchangedToken = useRef(false);

  // Load plan - Session Cookie Pattern
  useEffect(() => {
    const load = async () => {
      // Case 1: Fresh load with token in URL → Exchange for session
      if (token && !hasExchangedToken.current) {
        hasExchangedToken.current = true;

        const result = await exchangeTokenForSession(token);
        setState(result);

        // SECURITY: Strip token from URL after successful exchange
        if (result.status === "valid" && typeof window !== "undefined") {
          const url = new URL(window.location.href);
          url.searchParams.delete("t");
          window.history.replaceState({}, "", url.pathname);
        }

        // Record read if valid (debounced - only once per session)
        if (result.status === "valid" && !hasRecordedRead.current) {
          hasRecordedRead.current = true;
          setTimeout(() => {
            recordReadReceiptSession();
          }, 500);
        }
        return;
      }

      // Case 2: Refresh/Back without token → Check existing session
      if (!token) {
        const result = await getSessionPlan();

        // Special case: No session found → Show "need new link" message
        if (result.status === "error" && result.errorMessage === "no_session") {
          setState({
            status: "error",
            errorMessage: "Keine aktive Sitzung. Bitte verwenden Sie den Link aus Ihrer Nachricht.",
          });
          return;
        }

        setState(result);

        // Record read if valid (debounced - only once per session)
        if (result.status === "valid" && !hasRecordedRead.current) {
          hasRecordedRead.current = true;
          setTimeout(() => {
            recordReadReceiptSession();
          }, 500);
        }
      }
    };

    load();
  }, [token]);

  // Handle accept
  const handleAccept = useCallback(async () => {
    setIsSubmitting(true);
    setSubmitError(null);

    const result = await submitAcknowledgmentSession("ACCEPTED");

    if (result.success) {
      setState((prev) => ({ ...prev, ackStatus: "ACCEPTED" }));
    } else {
      setSubmitError(result.error || "Fehler beim Bestätigen");
    }

    setIsSubmitting(false);
  }, []);

  // Handle decline
  const handleDecline = useCallback(
    async (reason: string, freeText: string) => {
      setIsSubmitting(true);
      setSubmitError(null);

      const result = await submitAcknowledgmentSession("DECLINED", reason, freeText);

      if (result.success) {
        setState((prev) => ({ ...prev, ackStatus: "DECLINED" }));
        setShowDeclineModal(false);
      } else {
        setSubmitError(result.error || "Fehler beim Ablehnen");
      }

      setIsSubmitting(false);
    },
    []
  );

  // Render based on state
  if (state.status === "loading") {
    return <LoadingState />;
  }

  if (state.status === "expired") {
    return <ExpiredState />;
  }

  if (state.status === "error" || state.status === "revoked") {
    return <ErrorState message={state.errorMessage || "Unbekannter Fehler"} showRetry />;
  }

  if (state.status === "superseded") {
    return <SupersededState newSnapshotMessage={state.errorMessage || ""} />;
  }

  const { plan, ackStatus } = state;
  if (!plan) {
    return <ErrorState message="Plan konnte nicht geladen werden" showRetry />;
  }

  const isAcknowledged = ackStatus === "ACCEPTED" || ackStatus === "DECLINED";

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Header */}
      <header className="bg-slate-800/80 border-b border-slate-700 sticky top-0 z-10 backdrop-blur-sm">
        <div className="max-w-2xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center">
                <span className="text-white font-bold">S</span>
              </div>
              <div>
                <h1 className="text-lg font-bold text-white">Mein Schichtplan</h1>
                <p className="text-xs text-slate-400">
                  {plan.week_start} - {plan.week_end}
                </p>
              </div>
            </div>

            {/* Status Badge */}
            {ackStatus === "ACCEPTED" && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-500/20 border border-emerald-500/30 rounded-full">
                <CheckCircle className="w-4 h-4 text-emerald-400" />
                <span className="text-sm font-medium text-emerald-400">Bestätigt</span>
              </div>
            )}
            {ackStatus === "DECLINED" && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-500/20 border border-amber-500/30 rounded-full">
                <XCircle className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-medium text-amber-400">Abgelehnt</span>
              </div>
            )}
            {ackStatus === "PENDING" && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-500/20 border border-blue-500/30 rounded-full">
                <Clock className="w-4 h-4 text-blue-400" />
                <span className="text-sm font-medium text-blue-400">Ausstehend</span>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-2xl mx-auto px-4 py-6">
        {/* Driver Info */}
        <div className="bg-slate-800/50 rounded-xl p-4 mb-6 border border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-500">Fahrer</p>
              <p className="text-lg font-semibold text-white">{plan.driver_name}</p>
            </div>
            <div className="text-right">
              <p className="text-sm text-slate-500">Gesamt</p>
              <p className="text-lg font-semibold text-emerald-400">
                {plan.total_hours.toFixed(1)} Std.
              </p>
            </div>
          </div>
          {plan.message && (
            <p className="mt-3 pt-3 border-t border-slate-700 text-sm text-slate-400">
              {plan.message}
            </p>
          )}
        </div>

        {/* Shifts */}
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Calendar className="w-5 h-5 text-slate-500" />
          Ihre Schichten ({plan.shifts.length})
        </h2>

        <div className="space-y-3 mb-8">
          {plan.shifts.length === 0 ? (
            <div className="bg-slate-800/50 rounded-xl p-6 text-center border border-slate-700">
              <p className="text-slate-400">Keine Schichten in diesem Zeitraum</p>
            </div>
          ) : (
            plan.shifts.map((shift, i) => <ShiftCard key={i} shift={shift} />)
          )}
        </div>

        {/* Error Message */}
        {submitError && (
          <div className="mb-4 p-4 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm">
            {submitError}
          </div>
        )}

        {/* Action Buttons */}
        {!isAcknowledged && (
          <div className="fixed bottom-0 left-0 right-0 bg-slate-800/95 border-t border-slate-700 p-4 backdrop-blur-sm">
            <div className="max-w-2xl mx-auto flex gap-3">
              <button
                onClick={() => setShowDeclineModal(true)}
                disabled={isSubmitting}
                className="flex-1 px-6 py-4 bg-slate-700 hover:bg-slate-600 text-white rounded-xl font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <XCircle className="w-5 h-5" />
                Ablehnen
              </button>
              <button
                onClick={handleAccept}
                disabled={isSubmitting}
                className="flex-1 px-6 py-4 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Wird gesendet...
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-5 h-5" />
                    Bestätigen
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Acknowledged Message */}
        {isAcknowledged && (
          <div className="bg-slate-800/50 rounded-xl p-6 text-center border border-slate-700">
            {ackStatus === "ACCEPTED" ? (
              <>
                <CheckCircle className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
                <h3 className="text-lg font-semibold text-white mb-2">
                  Plan bestätigt
                </h3>
                <p className="text-slate-400">
                  Vielen Dank! Ihre Bestätigung wurde erfolgreich gespeichert.
                </p>
              </>
            ) : (
              <>
                <XCircle className="w-12 h-12 text-amber-400 mx-auto mb-3" />
                <h3 className="text-lg font-semibold text-white mb-2">
                  Plan abgelehnt
                </h3>
                <p className="text-slate-400">
                  Ihre Ablehnung wurde erfolgreich gespeichert. Die Disposition wird sich bei Ihnen melden.
                </p>
              </>
            )}
          </div>
        )}

        {/* Bottom padding for fixed action bar */}
        {!isAcknowledged && <div className="h-24" />}
      </main>

      {/* Decline Modal */}
      {showDeclineModal && (
        <DeclineModal
          onConfirm={handleDecline}
          onCancel={() => setShowDeclineModal(false)}
          isSubmitting={isSubmitting}
        />
      )}
    </div>
  );
}

// =============================================================================
// PAGE COMPONENT (with Suspense for useSearchParams)
// =============================================================================

export default function MyPlanPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <DriverPortalContent />
    </Suspense>
  );
}
