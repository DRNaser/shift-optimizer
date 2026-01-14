'use client';

import { useState, useEffect } from 'react';
import {
  X,
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  Users,
  Clock,
  Repeat,
  FileText,
  Loader2,
  Upload,
} from 'lucide-react';
import { generateIdempotencyKey, clearIdempotencyKey } from '@/lib/security/idempotency';

interface KpiDelta {
  metric: string;
  label: string;
  base_value: number | null;
  current_value: number;
  delta: number | null;
  unit: string;
}

interface AssignmentChange {
  driver_id: string;
  driver_name: string;
  day: string;
  change_type: 'ADDED' | 'REMOVED' | 'MODIFIED';
  base_tour: string | null;
  current_tour: string | null;
}

interface DiffData {
  plan_version_id: number;
  base_snapshot_id: number | null;
  base_version_number: number | null;
  kpi_deltas: KpiDelta[];
  changes: AssignmentChange[];
  churn_count: number;
  churn_percentage: number;
  can_publish: boolean;
  block_count: number;
  warn_count: number;
  reason_required: boolean;
}

interface DiffModalProps {
  planId: string;
  isOpen: boolean;
  onClose: () => void;
  onPublishSuccess?: () => void;
}

export function DiffModal({
  planId,
  isOpen,
  onClose,
  onPublishSuccess,
}: DiffModalProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [diffData, setDiffData] = useState<DiffData | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishReason, setPublishReason] = useState('');
  const [publishNote, setPublishNote] = useState('');

  useEffect(() => {
    if (!isOpen) return;

    async function fetchDiff() {
      setLoading(true);
      setError(null);

      try {
        const response = await fetch(`/api/roster/plans/${planId}/diff`);
        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.error || 'Failed to fetch diff');
        }
        const data = await response.json();
        setDiffData(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    fetchDiff();
  }, [planId, isOpen]);

  async function handlePublish() {
    if (!diffData?.can_publish) return;
    if (diffData.reason_required && !publishReason.trim()) {
      setError('Reason is required for publishing');
      return;
    }

    setPublishing(true);
    setError(null);

    try {
      const idempotencyKey = generateIdempotencyKey('roster.snapshot.publish', planId);

      const response = await fetch('/api/roster/snapshots/publish', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-idempotency-key': idempotencyKey,
        },
        body: JSON.stringify({
          plan_version_id: parseInt(planId, 10),
          reason: publishReason.trim() || 'Published from diff review',
          note: publishNote.trim() || undefined,
        }),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || err.detail || 'Failed to publish');
      }

      clearIdempotencyKey('roster.snapshot.publish', planId);
      onPublishSuccess?.();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Publish failed');
    } finally {
      setPublishing(false);
    }
  }

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/70 z-50" onClick={onClose} />

      {/* Modal */}
      <div className="fixed inset-4 md:inset-10 bg-slate-900 border border-slate-800 rounded-xl z-50 flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/80">
          <div className="flex items-center gap-3">
            <FileText className="w-5 h-5 text-slate-500" />
            <div>
              <h2 className="text-lg font-semibold text-white">Pre-Publish Review</h2>
              <p className="text-sm text-slate-500">
                Review changes before publishing snapshot
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <div className="flex flex-col items-center gap-4">
                <Loader2 className="w-8 h-8 text-slate-400 animate-spin" />
                <p className="text-slate-400">Computing diff...</p>
              </div>
            </div>
          ) : error ? (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 flex items-center gap-3 text-red-400">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <p>{error}</p>
            </div>
          ) : diffData ? (
            <div className="space-y-6">
              {/* Publish Gate Status */}
              <div
                className={`p-4 rounded-lg border flex items-center gap-3 ${
                  diffData.can_publish
                    ? 'bg-emerald-500/10 border-emerald-500/20'
                    : 'bg-red-500/10 border-red-500/20'
                }`}
              >
                {diffData.can_publish ? (
                  <>
                    <CheckCircle className="w-6 h-6 text-emerald-400" />
                    <div>
                      <p className="text-emerald-400 font-medium">Ready to Publish</p>
                      <p className="text-sm text-emerald-400/70">
                        All blockers resolved, snapshot can be published
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-6 h-6 text-red-400" />
                    <div>
                      <p className="text-red-400 font-medium">Cannot Publish</p>
                      <p className="text-sm text-red-400/70">
                        {diffData.block_count} blocker{diffData.block_count !== 1 ? 's' : ''} must
                        be resolved first
                      </p>
                    </div>
                  </>
                )}
              </div>

              {/* KPI Deltas */}
              <div>
                <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4" />
                  KPI Changes
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {diffData.kpi_deltas.map((kpi) => (
                    <KpiCard key={kpi.metric} kpi={kpi} />
                  ))}
                </div>
              </div>

              {/* Churn Summary */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
                <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
                  <Repeat className="w-4 h-4" />
                  Assignment Churn
                </h3>
                <div className="flex items-center gap-6">
                  <div>
                    <span className="text-2xl font-bold text-white">{diffData.churn_count}</span>
                    <span className="text-slate-500 ml-2">changes</span>
                  </div>
                  <div>
                    <span className="text-lg font-medium text-slate-300">
                      {diffData.churn_percentage.toFixed(1)}%
                    </span>
                    <span className="text-slate-500 ml-2">churn rate</span>
                  </div>
                  {diffData.base_version_number && (
                    <div className="text-sm text-slate-500">
                      vs. Snapshot v{diffData.base_version_number}
                    </div>
                  )}
                </div>
              </div>

              {/* Changes Table */}
              {diffData.changes.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
                    <Users className="w-4 h-4" />
                    Assignment Changes ({diffData.changes.length})
                  </h3>
                  <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden">
                    <div className="overflow-x-auto max-h-64">
                      <table className="w-full text-sm">
                        <thead className="bg-slate-900/50 sticky top-0">
                          <tr>
                            <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase">
                              Driver
                            </th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase">
                              Day
                            </th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase">
                              Change
                            </th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase">
                              From
                            </th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-slate-500 uppercase">
                              To
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-700/50">
                          {diffData.changes.slice(0, 50).map((change, idx) => (
                            <tr key={idx} className="hover:bg-slate-800/30">
                              <td className="px-4 py-2">
                                <span className="text-slate-300">{change.driver_name}</span>
                                <span className="text-slate-600 text-xs ml-1">
                                  ({change.driver_id})
                                </span>
                              </td>
                              <td className="px-4 py-2 text-slate-400 uppercase text-xs">
                                {change.day}
                              </td>
                              <td className="px-4 py-2">
                                <ChangeTypeBadge type={change.change_type} />
                              </td>
                              <td className="px-4 py-2 text-slate-500 font-mono text-xs">
                                {change.base_tour || '-'}
                              </td>
                              <td className="px-4 py-2 text-slate-300 font-mono text-xs">
                                {change.current_tour || '-'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {diffData.changes.length > 50 && (
                      <div className="px-4 py-2 text-xs text-slate-500 border-t border-slate-700/50">
                        Showing 50 of {diffData.changes.length} changes
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Publish Form */}
              {diffData.can_publish && (
                <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
                  <h3 className="text-sm font-medium text-white mb-3">Publish Details</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-400 mb-1">
                        Reason {diffData.reason_required && <span className="text-red-400">*</span>}
                      </label>
                      <select
                        value={publishReason}
                        onChange={(e) => setPublishReason(e.target.value)}
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-slate-600"
                      >
                        <option value="">Select reason...</option>
                        <option value="INITIAL_PUBLISH">Initial Publish</option>
                        <option value="SCHEDULE_UPDATE">Schedule Update</option>
                        <option value="DRIVER_REQUEST">Driver Request</option>
                        <option value="COVERAGE_FIX">Coverage Fix</option>
                        <option value="VIOLATION_RESOLUTION">Violation Resolution</option>
                        <option value="OTHER">Other</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-slate-400 mb-1">Note (optional)</label>
                      <textarea
                        value={publishNote}
                        onChange={(e) => setPublishNote(e.target.value)}
                        rows={2}
                        placeholder="Add a note for the audit trail..."
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-slate-600 resize-none"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-800 bg-slate-900/80 flex items-center justify-between">
          <div className="flex items-center gap-4 text-sm">
            {diffData && (
              <>
                <span className="flex items-center gap-1 text-red-400">
                  <AlertCircle className="w-4 h-4" />
                  {diffData.block_count} blockers
                </span>
                <span className="flex items-center gap-1 text-amber-400">
                  <AlertTriangle className="w-4 h-4" />
                  {diffData.warn_count} warnings
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-slate-400 hover:text-white border border-slate-700 rounded-lg hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            {diffData?.can_publish && (
              <button
                onClick={handlePublish}
                disabled={publishing || (diffData.reason_required && !publishReason)}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                {publishing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Upload className="w-4 h-4" />
                )}
                {publishing ? 'Publishing...' : 'Publish Snapshot'}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function KpiCard({ kpi }: { kpi: KpiDelta }) {
  const hasChange = kpi.delta !== null && kpi.delta !== 0;
  const isPositive = kpi.delta !== null && kpi.delta > 0;
  const isNegative = kpi.delta !== null && kpi.delta < 0;

  // Determine if positive is good or bad based on metric
  const positiveIsGood = !['violations', 'blockers', 'warnings', 'overtime'].some((m) =>
    kpi.metric.toLowerCase().includes(m)
  );

  const deltaColor = hasChange
    ? isPositive
      ? positiveIsGood
        ? 'text-emerald-400'
        : 'text-red-400'
      : positiveIsGood
      ? 'text-red-400'
      : 'text-emerald-400'
    : 'text-slate-500';

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-3">
      <p className="text-xs text-slate-500 mb-1">{kpi.label}</p>
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-semibold text-white">
          {kpi.current_value}
          {kpi.unit && <span className="text-sm text-slate-400 ml-0.5">{kpi.unit}</span>}
        </span>
        {hasChange && (
          <span className={`flex items-center text-xs ${deltaColor}`}>
            {isPositive ? (
              <TrendingUp className="w-3 h-3 mr-0.5" />
            ) : isNegative ? (
              <TrendingDown className="w-3 h-3 mr-0.5" />
            ) : (
              <Minus className="w-3 h-3 mr-0.5" />
            )}
            {isPositive ? '+' : ''}
            {kpi.delta}
          </span>
        )}
      </div>
      {kpi.base_value !== null && (
        <p className="text-xs text-slate-600 mt-1">
          was: {kpi.base_value}
          {kpi.unit}
        </p>
      )}
    </div>
  );
}

function ChangeTypeBadge({ type }: { type: 'ADDED' | 'REMOVED' | 'MODIFIED' }) {
  switch (type) {
    case 'ADDED':
      return (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-emerald-500/20 text-emerald-400">
          Added
        </span>
      );
    case 'REMOVED':
      return (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-500/20 text-red-400">
          Removed
        </span>
      );
    case 'MODIFIED':
      return (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-blue-500/20 text-blue-400">
          Changed
        </span>
      );
  }
}
