// =============================================================================
// SOLVEREIGN Platform Admin - Resolve Escalation Dialog
// =============================================================================
// Governance-controlled escalation resolution with severity-based requirements:
// - S0/S1: Type "RESOLVE" + mandatory comment (min 10 chars)
// - S2/S3: Simple confirm + optional comment
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, X, CheckCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

export interface ResolveEscalationDialogProps {
  escalation: {
    id: string;
    scope_type: 'platform' | 'org' | 'tenant' | 'site';
    scope_id: string | null;
    severity: 'S0' | 'S1' | 'S2' | 'S3';
    reason_code: string;
    reason_message: string;
  };
  onClose: () => void;
  onConfirm: (data: ResolveData) => Promise<void>;
}

export interface ResolveData {
  comment: string;
  incident_ref?: string;
}

// =============================================================================
// Constants
// =============================================================================

const CONFIRM_KEYWORD = 'RESOLVE';
const MIN_COMMENT_LENGTH = 10;
const HIGH_SEVERITY = ['S0', 'S1'];

// =============================================================================
// Component
// =============================================================================

export function ResolveEscalationDialog({
  escalation,
  onClose,
  onConfirm,
}: ResolveEscalationDialogProps) {
  const [confirmText, setConfirmText] = useState('');
  const [comment, setComment] = useState('');
  const [incidentRef, setIncidentRef] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isHighSeverity = HIGH_SEVERITY.includes(escalation.severity);

  // For S0/S1: require "RESOLVE" keyword AND comment >= 10 chars
  // For S2/S3: just need to click confirm (comment optional)
  const isConfirmValid = isHighSeverity
    ? confirmText === CONFIRM_KEYWORD && comment.length >= MIN_COMMENT_LENGTH
    : true;

  const getValidationMessage = useCallback(() => {
    if (!isHighSeverity) return null;

    const issues: string[] = [];
    if (confirmText !== CONFIRM_KEYWORD) {
      issues.push(`Type "${CONFIRM_KEYWORD}" to confirm`);
    }
    if (comment.length < MIN_COMMENT_LENGTH) {
      issues.push(`Comment must be at least ${MIN_COMMENT_LENGTH} characters (${comment.length}/${MIN_COMMENT_LENGTH})`);
    }
    return issues.length > 0 ? issues.join(' | ') : null;
  }, [isHighSeverity, confirmText, comment.length]);

  const handleSubmit = async () => {
    if (!isConfirmValid) return;

    setSubmitting(true);
    setError(null);

    try {
      await onConfirm({
        comment: comment.trim(),
        incident_ref: incidentRef.trim() || undefined,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resolve escalation');
      setSubmitting(false);
    }
  };

  // Close on escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, submitting]);

  const validationMessage = getValidationMessage();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={submitting ? undefined : onClose}
      />

      {/* Modal */}
      <div className="relative bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] w-full max-w-lg p-6 shadow-xl">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                'h-10 w-10 rounded-lg flex items-center justify-center',
                isHighSeverity ? 'bg-red-500/20' : 'bg-yellow-500/20'
              )}
            >
              <AlertTriangle
                className={cn(
                  'h-5 w-5',
                  isHighSeverity ? 'text-red-400' : 'text-yellow-400'
                )}
              />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">
                Resolve Escalation
              </h2>
              <p className="text-sm text-[var(--sv-gray-400)]">
                {escalation.severity} - {escalation.scope_type}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={submitting}
            className="text-[var(--sv-gray-400)] hover:text-white disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Escalation Info */}
        <div className="mb-6 p-4 bg-[var(--sv-gray-800)] rounded-lg">
          <p className="text-sm font-mono text-[var(--sv-gray-400)] mb-1">
            {escalation.reason_code}
          </p>
          <p className="text-white">{escalation.reason_message}</p>
        </div>

        {/* High Severity Warning */}
        {isHighSeverity && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
            <p className="text-sm text-red-400 font-medium mb-2">
              High Severity Resolution
            </p>
            <p className="text-sm text-[var(--sv-gray-400)]">
              This is a {escalation.severity} escalation. To resolve, you must:
            </p>
            <ul className="text-sm text-[var(--sv-gray-400)] mt-2 space-y-1 list-disc list-inside">
              <li>Type &quot;{CONFIRM_KEYWORD}&quot; to confirm</li>
              <li>Provide a resolution comment (minimum {MIN_COMMENT_LENGTH} characters)</li>
            </ul>
          </div>
        )}

        {/* Form Fields */}
        <div className="space-y-4">
          {/* Confirm Text (S0/S1 only) */}
          {isHighSeverity && (
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Type &quot;{CONFIRM_KEYWORD}&quot; to confirm
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value.toUpperCase())}
                placeholder={CONFIRM_KEYWORD}
                className={cn(
                  'w-full px-3 py-2 rounded-lg',
                  'bg-[var(--sv-gray-800)] border',
                  confirmText === CONFIRM_KEYWORD
                    ? 'border-green-500/50 text-green-400'
                    : 'border-[var(--sv-gray-600)] text-white',
                  'placeholder-[var(--sv-gray-500)]',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
                autoComplete="off"
                disabled={submitting}
              />
            </div>
          )}

          {/* Comment */}
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Resolution Comment {isHighSeverity ? '(Required)' : '(Optional)'}
            </label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={
                isHighSeverity
                  ? 'Describe the resolution action taken...'
                  : 'Optional: Add any notes about the resolution...'
              }
              rows={3}
              className={cn(
                'w-full px-3 py-2 rounded-lg resize-none',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
              disabled={submitting}
            />
            {isHighSeverity && (
              <p
                className={cn(
                  'text-xs mt-1',
                  comment.length >= MIN_COMMENT_LENGTH
                    ? 'text-green-400'
                    : 'text-[var(--sv-gray-500)]'
                )}
              >
                {comment.length}/{MIN_COMMENT_LENGTH} characters minimum
              </p>
            )}
          </div>

          {/* Incident Reference (Optional) */}
          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Incident Reference (Optional)
            </label>
            <input
              type="text"
              value={incidentRef}
              onChange={(e) => setIncidentRef(e.target.value)}
              placeholder="e.g., INC-12345, JIRA-123"
              className={cn(
                'w-full px-3 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
              disabled={submitting}
            />
          </div>
        </div>

        {/* Validation Message */}
        {validationMessage && (
          <p className="mt-4 text-sm text-yellow-400">{validationMessage}</p>
        )}

        {/* Error Message */}
        {error && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 mt-6">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className={cn(
              'flex-1 px-4 py-2 rounded-lg',
              'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
              'hover:bg-[var(--sv-gray-700)] transition-colors',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!isConfirmValid || submitting}
            className={cn(
              'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg',
              'bg-green-500/20 text-green-400 border border-green-500/30',
              'hover:bg-green-500/30 transition-colors',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {submitting ? (
              <>
                <div className="h-4 w-4 border-2 border-green-400/30 border-t-green-400 rounded-full animate-spin" />
                Resolving...
              </>
            ) : (
              <>
                <CheckCircle className="h-4 w-4" />
                Confirm Resolution
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
