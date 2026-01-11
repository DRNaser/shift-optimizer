'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  Plus,
  Trash2,
  Eye,
  Save,
  UserMinus,
  ArrowRight,
} from 'lucide-react';
import { generateIdempotencyKey, clearIdempotencyKey } from '@/lib/security/idempotency';
import type { RepairPreviewResponse, RepairSummary, AssignmentDiff, ViolationsList, ViolationEntry } from '@/lib/api/schemas';

interface PlanOption {
  id: number;
  status: string;
  plan_state: string;
  seed: number;
  created_at: string;
}

interface AbsenceFormEntry {
  id: string;
  driver_id: string;
  from: string;
  to: string;
  reason: string;
}

function generateUUID() {
  return crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getVerdictBadge(verdict: string) {
  switch (verdict) {
    case 'OK':
      return (
        <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
          <CheckCircle className="w-4 h-4" />
          OK
        </span>
      );
    case 'WARN':
      return (
        <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
          <AlertTriangle className="w-4 h-4" />
          Warning
        </span>
      );
    case 'BLOCK':
      return (
        <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium bg-red-500/20 text-red-400 border border-red-500/30">
          <XCircle className="w-4 h-4" />
          Blocked
        </span>
      );
    default:
      return null;
  }
}

export default function RepairPage() {
  // State for plan selection
  const [plans, setPlans] = useState<PlanOption[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<string>('');
  const [loadingPlans, setLoadingPlans] = useState(true);

  // State for absences
  const [absences, setAbsences] = useState<AbsenceFormEntry[]>([
    { id: generateUUID(), driver_id: '', from: '', to: '', reason: 'SICK' },
  ]);

  // State for preview/commit
  const [previewResult, setPreviewResult] = useState<RepairPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [commitLoading, setCommitLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [commitSuccess, setCommitSuccess] = useState<{ planId: number } | null>(null);

  // Fetch plans on mount
  useEffect(() => {
    async function fetchPlans() {
      try {
        const response = await fetch('/api/roster/plans');
        const data = await response.json();
        if (data.success && data.plans) {
          setPlans(data.plans);
          // Select the most recent plan by default
          if (data.plans.length > 0) {
            setSelectedPlanId(String(data.plans[0].id));
          }
        }
      } catch (e) {
        console.error('Failed to fetch plans:', e);
      } finally {
        setLoadingPlans(false);
      }
    }
    fetchPlans();
  }, []);

  // Add absence entry
  function addAbsence() {
    setAbsences([
      ...absences,
      { id: generateUUID(), driver_id: '', from: '', to: '', reason: 'SICK' },
    ]);
  }

  // Remove absence entry
  function removeAbsence(id: string) {
    if (absences.length > 1) {
      setAbsences(absences.filter((a) => a.id !== id));
    }
  }

  // Update absence entry
  function updateAbsence(id: string, field: keyof AbsenceFormEntry, value: string) {
    setAbsences(
      absences.map((a) => (a.id === id ? { ...a, [field]: value } : a))
    );
  }

  // Validate form
  function validateForm(): string | null {
    if (!selectedPlanId) {
      return 'Please select a base plan';
    }
    for (const absence of absences) {
      if (!absence.driver_id || !absence.from || !absence.to) {
        return 'Please fill in all absence fields';
      }
      if (isNaN(parseInt(absence.driver_id))) {
        return 'Driver ID must be a number';
      }
    }
    return null;
  }

  // Preview repair
  async function handlePreview() {
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    setPreviewLoading(true);
    setError(null);
    setPreviewResult(null);
    setCommitSuccess(null);

    try {
      const response = await fetch('/api/roster/repair/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base_plan_version_id: parseInt(selectedPlanId),
          absences: absences.map((a) => ({
            driver_id: parseInt(a.driver_id),
            from: a.from,
            to: a.to,
            reason: a.reason,
          })),
          objective: 'min_churn',
          seed: 94,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || data.detail?.message || 'Preview failed');
      }

      setPreviewResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setPreviewLoading(false);
    }
  }

  // Commit repair
  async function handleCommit() {
    if (!previewResult || previewResult.verdict === 'BLOCK') {
      return;
    }

    setCommitLoading(true);
    setError(null);

    try {
      // Generate stable idempotency key based on base plan + absence hash
      const absenceHash = absences
        .map((a) => `${a.driver_id}:${a.from}:${a.to}`)
        .sort()
        .join('|');
      const idempotencyKey = generateIdempotencyKey(
        'roster.repair.commit',
        `${selectedPlanId}:${absenceHash}`
      );

      const response = await fetch('/api/roster/repair/commit', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-idempotency-key': idempotencyKey,
        },
        body: JSON.stringify({
          base_plan_version_id: parseInt(selectedPlanId),
          absences: absences.map((a) => ({
            driver_id: parseInt(a.driver_id),
            from: a.from,
            to: a.to,
            reason: a.reason,
          })),
          objective: 'min_churn',
          seed: 94,
          commit_reason: `Repair: ${absences.length} absent driver(s)`,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || data.detail?.message || 'Commit failed');
      }

      // Clear idempotency key on success
      clearIdempotencyKey('roster.repair.commit', `${selectedPlanId}:${absenceHash}`);

      setCommitSuccess({ planId: data.new_plan_version_id });
      setPreviewResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Commit failed');
    } finally {
      setCommitLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link
            href="/packs/roster/plans"
            className="text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <UserMinus className="w-6 h-6 text-amber-500" />
              Repair Plan
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Handle sick calls and absences by creating a repaired plan version
            </p>
          </div>
        </div>

        {/* Success Message */}
        {commitSuccess && (
          <div className="mb-6 bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <CheckCircle className="w-5 h-5 text-emerald-400" />
              <div>
                <p className="text-emerald-400 font-medium">Repair committed successfully!</p>
                <p className="text-sm text-slate-400 mt-1">
                  New plan created:{' '}
                  <Link
                    href={`/packs/roster/plans/${commitSuccess.planId}`}
                    className="text-emerald-400 hover:underline"
                  >
                    Plan #{commitSuccess.planId}
                  </Link>
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="mb-6 bg-red-500/10 border border-red-500/20 rounded-lg p-4 flex items-center gap-3 text-red-400">
            <AlertTriangle className="w-5 h-5 shrink-0" />
            <p>{error}</p>
          </div>
        )}

        {/* Form Section */}
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold text-white mb-4">Repair Configuration</h2>

          {/* Plan Selection */}
          <div className="mb-6">
            <label className="block text-sm text-slate-400 mb-2">Base Plan Version</label>
            {loadingPlans ? (
              <div className="flex items-center gap-2 text-slate-500">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading plans...
              </div>
            ) : (
              <select
                value={selectedPlanId}
                onChange={(e) => setSelectedPlanId(e.target.value)}
                className="w-full bg-slate-700/50 border border-slate-600/50 rounded-lg px-4 py-2 text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="">Select a plan...</option>
                {plans.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    Plan #{plan.id} - {plan.plan_state} (Seed: {plan.seed}) -{' '}
                    {new Date(plan.created_at).toLocaleDateString()}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Absences */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm text-slate-400">Absences</label>
              <button
                onClick={addAbsence}
                className="flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300"
              >
                <Plus className="w-4 h-4" />
                Add Absence
              </button>
            </div>

            <div className="space-y-3">
              {absences.map((absence, index) => (
                <div
                  key={absence.id}
                  className="grid grid-cols-12 gap-3 items-end bg-slate-700/30 rounded-lg p-3"
                >
                  <div className="col-span-2">
                    <label className="block text-xs text-slate-500 mb-1">Driver ID</label>
                    <input
                      type="number"
                      value={absence.driver_id}
                      onChange={(e) => updateAbsence(absence.id, 'driver_id', e.target.value)}
                      placeholder="77"
                      className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div className="col-span-3">
                    <label className="block text-xs text-slate-500 mb-1">From</label>
                    <input
                      type="datetime-local"
                      value={absence.from}
                      onChange={(e) => updateAbsence(absence.id, 'from', e.target.value)}
                      className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div className="col-span-3">
                    <label className="block text-xs text-slate-500 mb-1">To</label>
                    <input
                      type="datetime-local"
                      value={absence.to}
                      onChange={(e) => updateAbsence(absence.id, 'to', e.target.value)}
                      className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div className="col-span-3">
                    <label className="block text-xs text-slate-500 mb-1">Reason</label>
                    <select
                      value={absence.reason}
                      onChange={(e) => updateAbsence(absence.id, 'reason', e.target.value)}
                      className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    >
                      <option value="SICK">Sick</option>
                      <option value="VACATION">Vacation</option>
                      <option value="UNAVAILABLE">Unavailable</option>
                    </select>
                  </div>
                  <div className="col-span-1">
                    {absences.length > 1 && (
                      <button
                        onClick={() => removeAbsence(absence.id)}
                        className="p-1.5 text-slate-500 hover:text-red-400 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Preview Button */}
          <button
            onClick={handlePreview}
            disabled={previewLoading || !selectedPlanId}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
          >
            {previewLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Eye className="w-4 h-4" />
            )}
            {previewLoading ? 'Computing...' : 'Preview Repair'}
          </button>
        </div>

        {/* Preview Results */}
        {previewResult && (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">Preview Results</h2>
              {getVerdictBadge(previewResult.verdict)}
            </div>

            {/* Verdict Banner */}
            {previewResult.verdict !== 'OK' && (
              <VerdictBanner
                verdict={previewResult.verdict}
                reasons={previewResult.verdict_reasons}
                violations={previewResult.violations}
              />
            )}

            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <SummaryCard
                label="Uncovered Before"
                value={previewResult.summary.uncovered_before}
                color="red"
              />
              <SummaryCard
                label="Uncovered After"
                value={previewResult.summary.uncovered_after}
                color={previewResult.summary.uncovered_after === 0 ? 'emerald' : 'amber'}
              />
              <SummaryCard
                label="Drivers Changed"
                value={previewResult.summary.churn_driver_count}
                color="blue"
              />
              <SummaryCard
                label="Assignments Changed"
                value={previewResult.summary.churn_assignment_count}
                color="purple"
              />
            </div>

            {/* Violations Summary Cards */}
            {(previewResult.summary.overlap_violations > 0 ||
              previewResult.summary.rest_violations > 0 ||
              previewResult.summary.freeze_violations > 0) && (
              <div className="grid grid-cols-3 gap-4 mb-6">
                <SummaryCard
                  label="Freeze Violations"
                  value={previewResult.summary.freeze_violations}
                  color={previewResult.summary.freeze_violations > 0 ? 'red' : 'emerald'}
                />
                <SummaryCard
                  label="Overlap Violations"
                  value={previewResult.summary.overlap_violations}
                  color={previewResult.summary.overlap_violations > 0 ? 'red' : 'emerald'}
                />
                <SummaryCard
                  label="Rest Time Violations"
                  value={previewResult.summary.rest_violations}
                  color={previewResult.summary.rest_violations > 0 ? 'amber' : 'emerald'}
                />
              </div>
            )}

            {/* Diff Tables */}
            <div className="space-y-4">
              {/* Removed Assignments */}
              {previewResult.diff.removed_assignments.length > 0 && (
                <DiffTable
                  title="Removed Assignments"
                  items={previewResult.diff.removed_assignments}
                  type="removed"
                />
              )}

              {/* Added Assignments */}
              {previewResult.diff.added_assignments.length > 0 && (
                <DiffTable
                  title="New Assignments"
                  items={previewResult.diff.added_assignments}
                  type="added"
                />
              )}
            </div>

            {/* Commit Button */}
            <div className="mt-6 flex items-center justify-between border-t border-slate-700/50 pt-4">
              <div className="text-sm text-slate-500">
                Evidence: <code className="text-slate-400">{previewResult.evidence_id}</code> |
                Policy: <code className="text-slate-400">{previewResult.policy_hash}</code>
              </div>
              <button
                onClick={handleCommit}
                disabled={commitLoading || previewResult.verdict === 'BLOCK'}
                className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
              >
                {commitLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                {commitLoading ? 'Committing...' : 'Commit Repair'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Summary Card Component
function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: 'red' | 'emerald' | 'amber' | 'blue' | 'purple';
}) {
  const colorClasses = {
    red: 'text-red-400',
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    blue: 'text-blue-400',
    purple: 'text-purple-400',
  };

  return (
    <div className="bg-slate-700/30 rounded-lg p-4">
      <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${colorClasses[color]}`}>{value}</p>
    </div>
  );
}

// Diff Table Component
function DiffTable({
  title,
  items,
  type,
}: {
  title: string;
  items: AssignmentDiff[];
  type: 'removed' | 'added';
}) {
  const bgColor = type === 'removed' ? 'bg-red-500/5' : 'bg-emerald-500/5';
  const borderColor = type === 'removed' ? 'border-red-500/20' : 'border-emerald-500/20';

  return (
    <div className={`${bgColor} border ${borderColor} rounded-lg overflow-hidden`}>
      <div className="px-4 py-2 border-b border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-300">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-500 text-xs uppercase">
              <th className="px-4 py-2 text-left">Tour</th>
              <th className="px-4 py-2 text-left">Day</th>
              <th className="px-4 py-2 text-left">Block</th>
              <th className="px-4 py-2 text-left">Driver</th>
              <th className="px-4 py-2 text-left">Reason</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr key={i} className="border-t border-slate-700/30">
                <td className="px-4 py-2 font-mono text-slate-300">
                  {item.tour_instance_id}
                </td>
                <td className="px-4 py-2 text-slate-400">Day {item.day}</td>
                <td className="px-4 py-2 text-slate-400">{item.block_id}</td>
                <td className="px-4 py-2">
                  {type === 'removed' ? (
                    <span className="text-red-400">{item.driver_id}</span>
                  ) : (
                    <span className="flex items-center gap-1">
                      <span className="text-slate-500">{item.driver_id || '-'}</span>
                      <ArrowRight className="w-3 h-3 text-slate-600" />
                      <span className="text-emerald-400">{item.new_driver_id}</span>
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-slate-500 text-xs">{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Verdict Banner Component - shows violations clearly
function VerdictBanner({
  verdict,
  reasons,
  violations,
}: {
  verdict: string;
  reasons: string[];
  violations: ViolationsList;
}) {
  const isBlock = verdict === 'BLOCK';
  const bgColor = isBlock ? 'bg-red-500/10' : 'bg-amber-500/10';
  const borderColor = isBlock ? 'border-red-500/20' : 'border-amber-500/20';
  const textColor = isBlock ? 'text-red-400' : 'text-amber-400';
  const Icon = isBlock ? XCircle : AlertTriangle;

  const totalViolations =
    violations.overlap.length + violations.rest.length + violations.freeze.length;

  return (
    <div className={`mb-4 ${bgColor} border ${borderColor} rounded-lg p-4`}>
      <div className="flex items-start gap-3">
        <Icon className={`w-5 h-5 ${textColor} shrink-0 mt-0.5`} />
        <div className="flex-1 min-w-0">
          <p className={`font-medium ${textColor}`}>
            {isBlock
              ? 'Repair Blocked - Cannot Commit'
              : 'Repair has warnings - Review before committing'}
          </p>

          {/* Verdict Reasons */}
          {reasons.length > 0 && (
            <ul className="mt-2 list-disc list-inside text-sm text-slate-400">
              {reasons.map((reason, i) => (
                <li key={i}>{reason}</li>
              ))}
            </ul>
          )}

          {/* Violations Detail */}
          {totalViolations > 0 && (
            <div className="mt-3 space-y-2">
              {/* Freeze Violations */}
              {violations.freeze.length > 0 && (
                <ViolationGroup
                  title="Freeze Violations"
                  items={violations.freeze}
                  severity="BLOCK"
                />
              )}

              {/* Overlap Violations */}
              {violations.overlap.length > 0 && (
                <ViolationGroup
                  title="Overlap Violations"
                  items={violations.overlap}
                  severity="BLOCK"
                />
              )}

              {/* Rest Time Violations */}
              {violations.rest.length > 0 && (
                <ViolationGroup
                  title="Rest Time Violations"
                  items={violations.rest}
                  severity="WARN"
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Violation Group Component
function ViolationGroup({
  title,
  items,
  severity,
}: {
  title: string;
  items: ViolationEntry[];
  severity: 'BLOCK' | 'WARN';
}) {
  const bgColor = severity === 'BLOCK' ? 'bg-red-500/10' : 'bg-amber-500/10';
  const borderColor = severity === 'BLOCK' ? 'border-red-500/30' : 'border-amber-500/30';
  const textColor = severity === 'BLOCK' ? 'text-red-300' : 'text-amber-300';
  const badgeColor =
    severity === 'BLOCK'
      ? 'bg-red-500/20 text-red-400 border-red-500/30'
      : 'bg-amber-500/20 text-amber-400 border-amber-500/30';

  return (
    <div className={`${bgColor} border ${borderColor} rounded p-2`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`text-xs font-medium ${textColor}`}>{title}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border ${badgeColor}`}
        >
          {severity}
        </span>
        <span className="text-xs text-slate-500">({items.length})</span>
      </div>
      <ul className="space-y-1 text-xs text-slate-400">
        {items.slice(0, 5).map((item, i) => (
          <li key={i} className="flex items-start gap-1">
            <span className="text-slate-600">•</span>
            <span>{item.message}</span>
          </li>
        ))}
        {items.length > 5 && (
          <li className="text-slate-500 italic">
            ... and {items.length - 5} more
          </li>
        )}
      </ul>
    </div>
  );
}
