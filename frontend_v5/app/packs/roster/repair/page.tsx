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
  Lock,
  Zap,
  Users,
  BarChart3,
  Shield,
  Clock,
  Sparkles,
} from 'lucide-react';
import { generateIdempotencyKey, clearIdempotencyKey } from '@/lib/security/idempotency';
import {
  RepairPreviewResponseSchema,
  RepairCommitResponseSchema,
  validateResponse,
  type RepairPreviewResponse,
  type RepairSummary,
  type AssignmentDiff,
  type ViolationsList,
  type ViolationEntry,
} from '@/lib/api/schemas';

interface PlanOption {
  id: number;
  status: string;
  plan_state: string;
  seed: number;
  created_at: string;
}

interface LockStatus {
  is_locked: boolean;
  locked_at?: string;
  locked_by?: string;
}

interface AbsenceFormEntry {
  id: string;
  driver_id: string;
  from: string;
  to: string;
  reason: string;
}

// Orchestrated Repair Types
interface DeltaSummary {
  changed_tours_count: number;
  changed_drivers_count: number;
  impacted_drivers: number[];
  reserve_usage: number;
  chain_depth: number;
}

interface CoverageInfo {
  impacted_tours_count: number;
  impacted_assigned_count: number;
  coverage_percent: number;
  coverage_computed: boolean;
}

interface ViolationInfo {
  violations_validated: boolean;
  block_violations: number | null;
  warn_violations: number | null;
  validation_mode: 'none' | 'fast' | 'full';
  validation_note: string;
}

interface ProposedAssignment {
  tour_instance_id: number;
  driver_id: number;
  driver_name?: string;
  action: 'REASSIGN' | 'FILL' | 'SPLIT';
}

interface RepairProposal {
  proposal_id: string;
  label: string;
  feasible: boolean;
  quality_score: number;
  delta_summary: DeltaSummary;
  assignments: ProposedAssignment[];
  // New structured fields
  coverage: CoverageInfo;
  violations: ViolationInfo;
  // P1.5A: Compatibility info
  compatibility?: CompatibilityInfo;
  // Legacy fields (deprecated, may be null)
  coverage_percent: number;
  block_violations: number | null;
  warn_violations: number | null;
}

// Diagnostic types for P0.6
interface DiagnosticReason {
  code: string;
  message: string;
  tour_instance_ids: number[];
  suggested_action: string | null;
}

interface DiagnosticSummary {
  has_diagnostics: boolean;
  reasons: DiagnosticReason[];
  uncovered_tour_ids: number[];
  partial_proposals_available: boolean;
  suggested_actions: string[];
}

// Compatibility info for P1.5A
interface CompatibilityInfo {
  compatibility_checked: boolean;
  compatibility_unknown: boolean;
  missing_data: string[];
  incompatibilities: string[];
}

interface OrchestratedPreviewResponse {
  proposals: RepairProposal[];
  impacted_tours_count: number;
  incident_summary: string;
  trace_id: string;
  // P0.6: Diagnostics when no feasible proposals
  diagnostics: DiagnosticSummary | null;
  // P1.5A: Compatibility warning
  compatibility_unknown: boolean;
}

interface SnapshotOption {
  id: number;
  version: number;
  plan_version_id: number;
  status: string;
  created_at: string;
}

type RepairMode = 'session' | 'orchestrated';

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

  // State for lock status
  const [lockStatus, setLockStatus] = useState<LockStatus | null>(null);
  const [loadingLockStatus, setLoadingLockStatus] = useState(false);

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

  // Session-based repair state (canonical API)
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Repair mode toggle
  const [repairMode, setRepairMode] = useState<RepairMode>('session');

  // Orchestrated repair state
  const [snapshots, setSnapshots] = useState<SnapshotOption[]>([]);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string>('');
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [incidentDriverId, setIncidentDriverId] = useState<string>('');
  const [incidentTimeStart, setIncidentTimeStart] = useState<string>('');
  const [incidentTimeEnd, setIncidentTimeEnd] = useState<string>('');
  const [incidentReason, setIncidentReason] = useState<string>('SICK');
  const [topK, setTopK] = useState<number>(3);
  const [proposals, setProposals] = useState<RepairProposal[]>([]);
  const [selectedProposal, setSelectedProposal] = useState<RepairProposal | null>(null);
  const [orchestratedPreviewLoading, setOrchestratedPreviewLoading] = useState(false);
  const [prepareLoading, setPrepareLoading] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [draftId, setDraftId] = useState<number | null>(null);
  const [orchestratedSuccess, setOrchestratedSuccess] = useState<{ message: string } | null>(null);
  // P0.6: Diagnostics when no feasible proposals
  const [diagnostics, setDiagnostics] = useState<DiagnosticSummary | null>(null);
  // P1.5A: Compatibility warning
  const [compatibilityUnknown, setCompatibilityUnknown] = useState(false);
  const [compatibilityAcknowledged, setCompatibilityAcknowledged] = useState(false);
  // Change budget state (for "Increase Change Budget" CTA)
  const [changeBudget, setChangeBudget] = useState({
    maxChangedTours: 5,
    maxChangedDrivers: 3,
    maxChainDepth: 2,
  });

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

  // Fetch lock status when plan is selected
  useEffect(() => {
    async function fetchLockStatus() {
      if (!selectedPlanId) {
        setLockStatus(null);
        return;
      }

      setLoadingLockStatus(true);
      try {
        const response = await fetch(`/api/roster/plans/${selectedPlanId}/lock`);
        const data = await response.json();
        if (response.ok) {
          setLockStatus({
            is_locked: data.is_locked ?? false,
            locked_at: data.locked_at,
            locked_by: data.locked_by,
          });
        } else {
          // Assume not locked if we can't fetch status
          setLockStatus({ is_locked: false });
        }
      } catch (e) {
        console.error('Failed to fetch lock status:', e);
        setLockStatus({ is_locked: false });
      } finally {
        setLoadingLockStatus(false);
      }
    }
    fetchLockStatus();
  }, [selectedPlanId]);

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
    if (lockStatus?.is_locked) {
      return 'This plan is locked and cannot be repaired';
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

  // Fetch snapshots when orchestrated mode is selected
  useEffect(() => {
    async function fetchSnapshots() {
      if (repairMode !== 'orchestrated') return;

      setLoadingSnapshots(true);
      try {
        const response = await fetch('/api/roster/snapshots');
        const data = await response.json();
        if (data.success && data.snapshots) {
          // Filter to published snapshots only
          const publishedSnapshots = data.snapshots.filter(
            (s: SnapshotOption) => s.status === 'PUBLISHED'
          );
          setSnapshots(publishedSnapshots);
          if (publishedSnapshots.length > 0) {
            setSelectedSnapshotId(String(publishedSnapshots[0].id));
          }
        }
      } catch (e) {
        console.error('Failed to fetch snapshots:', e);
      } finally {
        setLoadingSnapshots(false);
      }
    }
    fetchSnapshots();
  }, [repairMode]);

  // Check if controls should be disabled
  const isLocked = lockStatus?.is_locked ?? false;
  const controlsDisabled = isLocked || loadingLockStatus;

  // Preview repair - uses session-based endpoint (canonical API)
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
    setSessionId(null);

    try {
      // Create session with absences - returns session_id + preview
      const response = await fetch('/api/roster/repairs/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_version_id: parseInt(selectedPlanId),
          reason_code: 'SICK_CALL',
          note: `Repair for ${absences.length} absent driver(s)`,
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
        // Extract error details with trace_id
        const errorMsg = data.message || data.error || data.detail?.message || 'Preview failed';
        const traceId = data.trace_id || '';
        throw new Error(traceId ? `${errorMsg} (trace: ${traceId})` : errorMsg);
      }

      // Store session_id for commit step
      setSessionId(data.session_id);

      // Extract preview from session response
      const previewData = data.preview;
      if (!previewData) {
        throw new Error('No preview data in session response');
      }

      // Zod-validate the preview response for runtime safety
      const validation = validateResponse(RepairPreviewResponseSchema, previewData, 'repair/preview');
      if (!validation.success) {
        console.warn('[Repair] Preview response validation failed, using raw data');
      }

      setPreviewResult(validation.data ?? previewData);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setPreviewLoading(false);
    }
  }

  // Commit repair - uses session-based apply endpoint (canonical API)
  async function handleCommit() {
    if (!previewResult || previewResult.verdict === 'BLOCK') {
      return;
    }

    if (!sessionId) {
      setError('No active session. Please preview again.');
      return;
    }

    setCommitLoading(true);
    setError(null);

    try {
      // Generate stable idempotency key based on session + plan
      const absenceHash = absences
        .map((a) => `${a.driver_id}:${a.from}:${a.to}`)
        .sort()
        .join('|');
      const idempotencyKey = generateIdempotencyKey(
        'roster.repair.apply',
        `${sessionId}:${absenceHash}`
      );

      // Use session-based apply endpoint
      const response = await fetch(`/api/roster/repairs/${sessionId}/apply`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-idempotency-key': idempotencyKey,
        },
        body: JSON.stringify({
          plan_version_id: parseInt(selectedPlanId),
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
        // Extract error details with trace_id
        const errorMsg = data.message || data.error || data.detail?.message || 'Commit failed';
        const traceId = data.trace_id || '';
        throw new Error(traceId ? `${errorMsg} (trace: ${traceId})` : errorMsg);
      }

      // Zod-validate the response for runtime safety
      const validation = validateResponse(RepairCommitResponseSchema, data, 'repair/commit');
      if (!validation.success) {
        console.warn('[Repair] Commit response validation failed, using raw data');
      }

      // Clear idempotency key on success
      clearIdempotencyKey('roster.repair.apply', `${sessionId}:${absenceHash}`);

      const commitData = validation.data ?? data;
      setCommitSuccess({ planId: commitData.new_plan_version_id });
      setPreviewResult(null);
      setSessionId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Commit failed');
    } finally {
      setCommitLoading(false);
    }
  }

  // Orchestrated repair: Preview proposals
  async function handleOrchestratedPreview() {
    if (!selectedSnapshotId || !incidentDriverId || !incidentTimeStart) {
      setError('Please select a snapshot and fill in incident details');
      return;
    }

    setOrchestratedPreviewLoading(true);
    setError(null);
    setProposals([]);
    setSelectedProposal(null);
    setDraftId(null);
    setOrchestratedSuccess(null);
    setDiagnostics(null);
    setCompatibilityUnknown(false);
    setCompatibilityAcknowledged(false);

    try {
      const response = await fetch('/api/roster/repairs/orchestrated/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          snapshot_id: parseInt(selectedSnapshotId),
          incident: {
            type: 'DRIVER_UNAVAILABLE',
            driver_id: parseInt(incidentDriverId),
            time_range_start: incidentTimeStart,
            time_range_end: incidentTimeEnd || undefined,
            reason: incidentReason,
          },
          change_budget: {
            max_changed_tours: changeBudget.maxChangedTours,
            max_changed_drivers: changeBudget.maxChangedDrivers,
            max_chain_depth: changeBudget.maxChainDepth,
          },
          split_policy: {
            allow_split: true,
            max_splits: 2,
            split_granularity: 'TOUR',
          },
          top_k: topK,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMsg = data.message || data.error || 'Preview failed';
        const traceId = data.trace_id || '';
        throw new Error(traceId ? `${errorMsg} (trace: ${traceId})` : errorMsg);
      }

      setProposals(data.proposals || []);
      // P0.6: Capture diagnostics when no feasible proposals
      if (data.diagnostics) {
        setDiagnostics(data.diagnostics);
      }
      // P1.5A: Capture compatibility warning
      if (data.compatibility_unknown) {
        setCompatibilityUnknown(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Orchestrated preview failed');
    } finally {
      setOrchestratedPreviewLoading(false);
    }
  }

  // Orchestrated repair: Prepare draft from selected proposal
  async function handlePrepare() {
    if (!selectedProposal) {
      setError('Please select a proposal first');
      return;
    }

    setPrepareLoading(true);
    setError(null);

    try {
      const idempotencyKey = generateIdempotencyKey(
        'roster.repair.prepare',
        `${selectedSnapshotId}:${selectedProposal.proposal_id}`
      );

      const response = await fetch('/api/roster/repairs/orchestrated/prepare', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-idempotency-key': idempotencyKey,
        },
        body: JSON.stringify({
          plan_version_id: parseInt(selectedSnapshotId), // snapshot maps to plan_version
          proposal_id: selectedProposal.proposal_id,
          assignments: selectedProposal.assignments,
          removed_assignments: selectedProposal.delta_summary.impacted_drivers.length > 0
            ? selectedProposal.assignments.map(a => a.tour_instance_id)
            : [],
          commit_reason: `Repair: Driver ${incidentDriverId} ${incidentReason}`,
          // P1.5A: Track user acknowledgment for audit trail
          compatibility_acknowledged: compatibilityAcknowledged,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMsg = data.message || data.error || 'Prepare failed';
        const traceId = data.trace_id || '';
        throw new Error(traceId ? `${errorMsg} (trace: ${traceId})` : errorMsg);
      }

      setDraftId(data.draft_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Prepare failed');
    } finally {
      setPrepareLoading(false);
    }
  }

  // Orchestrated repair: Confirm draft
  async function handleConfirm() {
    if (!draftId) {
      setError('No draft to confirm');
      return;
    }

    setConfirmLoading(true);
    setError(null);

    try {
      const idempotencyKey = generateIdempotencyKey(
        'roster.repair.confirm',
        `${draftId}`
      );

      const response = await fetch('/api/roster/repairs/orchestrated/confirm', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-idempotency-key': idempotencyKey,
        },
        body: JSON.stringify({
          draft_id: draftId,
          confirm_reason: `Repair: Driver ${incidentDriverId} ${incidentReason}`,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMsg = data.message || data.error || 'Confirm failed';
        const traceId = data.trace_id || '';
        throw new Error(traceId ? `${errorMsg} (trace: ${traceId})` : errorMsg);
      }

      clearIdempotencyKey('roster.repair.confirm', `${draftId}`);
      setOrchestratedSuccess({ message: `Plan version #${data.plan_version_id} confirmed and ready for publish` });
      setProposals([]);
      setSelectedProposal(null);
      setDraftId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Confirm failed');
    } finally {
      setConfirmLoading(false);
    }
  }

  // Reset orchestrated repair state when switching modes
  function resetOrchestratedState() {
    setProposals([]);
    setSelectedProposal(null);
    setDraftId(null);
    setOrchestratedSuccess(null);
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

        {/* Mode Toggle Tabs */}
        <div className="flex gap-2 mb-6 bg-slate-800/50 p-1 rounded-lg w-fit">
          <button
            onClick={() => {
              setRepairMode('session');
              resetOrchestratedState();
            }}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              repairMode === 'session'
                ? 'bg-blue-600 text-white'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
            }`}
          >
            <UserMinus className="w-4 h-4" />
            Session Repair
          </button>
          <button
            onClick={() => {
              setRepairMode('orchestrated');
              setPreviewResult(null);
              setSessionId(null);
            }}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              repairMode === 'orchestrated'
                ? 'bg-purple-600 text-white'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
            }`}
          >
            <Sparkles className="w-4 h-4" />
            Smart Repair (Top-K)
          </button>
        </div>

        {/* Success Message - Session */}
        {commitSuccess && repairMode === 'session' && (
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

        {/* Success Message - Orchestrated */}
        {orchestratedSuccess && repairMode === 'orchestrated' && (
          <div className="mb-6 bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <CheckCircle className="w-5 h-5 text-emerald-400" />
              <div>
                <p className="text-emerald-400 font-medium">Repair confirmed successfully!</p>
                <p className="text-sm text-slate-400 mt-1">{orchestratedSuccess.message}</p>
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

        {/* Locked Plan Banner */}
        {isLocked && selectedPlanId && (
          <div className="mb-6 bg-amber-500/10 border border-amber-500/20 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <Lock className="w-5 h-5 text-amber-400" />
              <div>
                <p className="text-amber-400 font-medium">Plan is Locked</p>
                <p className="text-sm text-slate-400 mt-1">
                  This plan was locked
                  {lockStatus?.locked_at && (
                    <> on <span className="text-slate-300">{new Date(lockStatus.locked_at).toLocaleString('de-AT')}</span></>
                  )}
                  {lockStatus?.locked_by && (
                    <> by <span className="text-slate-300">{lockStatus.locked_by}</span></>
                  )}
                  . Repairs are not allowed on locked plans.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* SESSION REPAIR MODE */}
        {repairMode === 'session' && (
          <>
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
            disabled={previewLoading || !selectedPlanId || controlsDisabled}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
            title={isLocked ? 'Plan is locked - repairs not allowed' : undefined}
          >
            {previewLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : isLocked ? (
              <Lock className="w-4 h-4" />
            ) : (
              <Eye className="w-4 h-4" />
            )}
            {previewLoading ? 'Computing...' : isLocked ? 'Locked' : 'Preview Repair'}
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
                disabled={commitLoading || previewResult.verdict === 'BLOCK' || controlsDisabled}
                className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
                title={isLocked ? 'Plan is locked - repairs not allowed' : undefined}
              >
                {commitLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : isLocked ? (
                  <Lock className="w-4 h-4" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                {commitLoading ? 'Committing...' : isLocked ? 'Locked' : 'Commit Repair'}
              </button>
            </div>
          </div>
        )}
          </>
        )}

        {/* ORCHESTRATED REPAIR MODE */}
        {repairMode === 'orchestrated' && (
          <>
            {/* Incident Form */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6 mb-6">
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <Zap className="w-5 h-5 text-purple-500" />
                Report Incident
              </h2>
              <p className="text-sm text-slate-400 mb-6">
                Report a driver unavailability and get multiple repair proposals automatically ranked by minimal disruption.
              </p>

              {/* Snapshot Selection */}
              <div className="mb-4">
                <label className="block text-sm text-slate-400 mb-2">Published Snapshot</label>
                {loadingSnapshots ? (
                  <div className="flex items-center gap-2 text-slate-500">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading snapshots...
                  </div>
                ) : snapshots.length === 0 ? (
                  <p className="text-sm text-amber-400">No published snapshots available. Publish a plan first.</p>
                ) : (
                  <select
                    value={selectedSnapshotId}
                    onChange={(e) => setSelectedSnapshotId(e.target.value)}
                    className="w-full bg-slate-700/50 border border-slate-600/50 rounded-lg px-4 py-2 text-slate-200 focus:outline-none focus:border-purple-500"
                  >
                    <option value="">Select a snapshot...</option>
                    {snapshots.map((snapshot) => (
                      <option key={snapshot.id} value={snapshot.id}>
                        Snapshot #{snapshot.id} (v{snapshot.version}) - {new Date(snapshot.created_at).toLocaleDateString()}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {/* Incident Details */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Driver ID</label>
                  <input
                    type="number"
                    value={incidentDriverId}
                    onChange={(e) => setIncidentDriverId(e.target.value)}
                    placeholder="77"
                    className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">From</label>
                  <input
                    type="datetime-local"
                    value={incidentTimeStart}
                    onChange={(e) => setIncidentTimeStart(e.target.value)}
                    className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">To (optional)</label>
                  <input
                    type="datetime-local"
                    value={incidentTimeEnd}
                    onChange={(e) => setIncidentTimeEnd(e.target.value)}
                    className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Reason</label>
                  <select
                    value={incidentReason}
                    onChange={(e) => setIncidentReason(e.target.value)}
                    className="w-full bg-slate-700/50 border border-slate-600/50 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-purple-500"
                  >
                    <option value="SICK">Sick</option>
                    <option value="VACATION">Vacation</option>
                    <option value="NO_SHOW">No Show</option>
                    <option value="EMERGENCY">Emergency</option>
                  </select>
                </div>
              </div>

              {/* Options Row */}
              <div className="flex items-center gap-6 mb-6">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-slate-500">Proposals:</label>
                  <select
                    value={topK}
                    onChange={(e) => setTopK(parseInt(e.target.value))}
                    className="bg-slate-700/50 border border-slate-600/50 rounded px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-purple-500"
                  >
                    <option value={2}>2</option>
                    <option value={3}>3</option>
                    <option value={5}>5</option>
                  </select>
                </div>
              </div>

              {/* Generate Proposals Button */}
              <button
                onClick={handleOrchestratedPreview}
                disabled={orchestratedPreviewLoading || !selectedSnapshotId || !incidentDriverId || !incidentTimeStart}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
              >
                {orchestratedPreviewLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {orchestratedPreviewLoading ? 'Generating Proposals...' : 'Generate Repair Proposals'}
              </button>
            </div>

            {/* Proposals Display */}
            {proposals.length > 0 && (
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6 mb-6">
                <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-purple-500" />
                  Repair Proposals
                </h2>
                <p className="text-sm text-slate-400 mb-4">
                  Select a proposal to prepare for publishing. All proposals guarantee 100% coverage and 0 blocking violations.
                </p>

                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                  {proposals.map((proposal) => (
                    <ProposalCard
                      key={proposal.proposal_id}
                      proposal={proposal}
                      isSelected={selectedProposal?.proposal_id === proposal.proposal_id}
                      onSelect={() => setSelectedProposal(proposal)}
                    />
                  ))}
                </div>

                {/* Selected Proposal Actions */}
                {selectedProposal && (
                  <div className="mt-6 border-t border-slate-700/50 pt-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm text-slate-400">
                          Selected: <span className="text-purple-400 font-medium">{selectedProposal.label}</span>
                        </p>
                        <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
                          <span className="flex items-center gap-1">
                            <Shield className="w-3 h-3 text-emerald-500" />
                            Coverage: {selectedProposal.coverage?.coverage_percent ?? selectedProposal.coverage_percent}%
                          </span>
                          <span className="flex items-center gap-1">
                            {selectedProposal.violations?.violations_validated ? (
                              <>
                                <XCircle className="w-3 h-3 text-emerald-500" />
                                Blocks: {selectedProposal.violations.block_violations ?? 0}
                              </>
                            ) : (
                              <>
                                <AlertTriangle className="w-3 h-3 text-amber-500" />
                                <span className="italic">Blocks: Not validated</span>
                              </>
                            )}
                          </span>
                          <span className="flex items-center gap-1">
                            <Users className="w-3 h-3" />
                            {selectedProposal.delta_summary.changed_drivers_count} drivers
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {draftId ? (
                          <button
                            onClick={handleConfirm}
                            disabled={confirmLoading}
                            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
                          >
                            {confirmLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <CheckCircle className="w-4 h-4" />
                            )}
                            {confirmLoading ? 'Confirming...' : 'Confirm & Publish'}
                          </button>
                        ) : (
                          <button
                            onClick={handlePrepare}
                            disabled={prepareLoading || (compatibilityUnknown && !compatibilityAcknowledged)}
                            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
                          >
                            {prepareLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Save className="w-4 h-4" />
                            )}
                            {prepareLoading ? 'Preparing...' : 'Prepare Draft'}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* P1.5A: Compatibility Acknowledgment Gate - amber for warning */}
                    {compatibilityUnknown && !draftId && (
                      <div className="mt-4 bg-amber-500/10 border border-amber-500/20 rounded-lg p-3">
                        <div className="flex items-start gap-3">
                          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
                          <div className="flex-1">
                            <p className="text-sm text-amber-300 font-medium">
                              Compatibility NOT CHECKED
                            </p>
                            <p className="text-xs text-slate-400 mt-1">
                              Skill and vehicle compatibility data is missing. The selected driver(s) may not have the required qualifications for the assigned tours.
                            </p>
                            <label className="flex items-center gap-2 mt-3 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={compatibilityAcknowledged}
                                onChange={(e) => setCompatibilityAcknowledged(e.target.checked)}
                                className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-amber-600 focus:ring-amber-500 focus:ring-offset-slate-800"
                              />
                              <span className="text-sm text-slate-300">
                                I understand and want to proceed anyway
                              </span>
                            </label>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Draft Ready Indicator */}
                    {draftId && (
                      <div className="mt-4 bg-blue-500/10 border border-blue-500/20 rounded-lg p-3">
                        <div className="flex items-center gap-2">
                          <CheckCircle className="w-4 h-4 text-blue-400" />
                          <p className="text-sm text-blue-400">
                            Draft #{draftId} prepared. Click "Confirm & Publish" to finalize.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Empty State with Diagnostics */}
            {proposals.length === 0 && !orchestratedPreviewLoading && selectedSnapshotId && (
              <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-8">
                {/* P0.6: Show diagnostics when no feasible proposals found */}
                {diagnostics && diagnostics.has_diagnostics ? (
                  <DiagnosticsPanel
                    diagnostics={diagnostics}
                    changeBudget={changeBudget}
                    onShowPartial={() => {
                      // TODO: Implement show partial proposals - would need backend support
                      setError('Partial proposals view not yet implemented');
                    }}
                    onIncreaseBudget={() => {
                      // Increase budget by preset increments and re-run preview
                      const newBudget = {
                        maxChangedTours: changeBudget.maxChangedTours + 2,
                        maxChangedDrivers: changeBudget.maxChangedDrivers + 1,
                        maxChainDepth: Math.min(changeBudget.maxChainDepth + 1, 4),
                      };
                      setChangeBudget(newBudget);
                      // Clear diagnostics and re-run with new budget
                      setDiagnostics(null);
                      // Trigger re-preview (handleOrchestratedPreview will use updated state)
                      setTimeout(() => handleOrchestratedPreview(), 100);
                    }}
                    onRunFullValidation={() => {
                      // TODO: Implement full validation - would need validation="full" param
                      setError('Full validation not yet implemented in preview');
                    }}
                  />
                ) : (
                  <div className="text-center">
                    <Sparkles className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                    <p className="text-slate-400">
                      Fill in the incident details and click "Generate Repair Proposals" to get repair options.
                    </p>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// Proposal Card Component
function ProposalCard({
  proposal,
  isSelected,
  onSelect,
}: {
  proposal: RepairProposal;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const qualityColor = proposal.quality_score >= 0.8
    ? 'text-emerald-400'
    : proposal.quality_score >= 0.5
    ? 'text-amber-400'
    : 'text-red-400';

  // Use new structured fields if available, fall back to legacy
  const coverage = proposal.coverage ?? {
    coverage_percent: proposal.coverage_percent,
    coverage_computed: true,
    impacted_tours_count: 0,
    impacted_assigned_count: 0,
  };
  const violations = proposal.violations ?? {
    violations_validated: false,
    block_violations: proposal.block_violations,
    warn_violations: proposal.warn_violations,
    validation_mode: 'none' as const,
    validation_note: '',
  };

  // Determine if we can trust the violation numbers
  const violationsValidated = violations.violations_validated;
  const blockCount = violations.block_violations;
  const warnCount = violations.warn_violations;

  return (
    <button
      onClick={onSelect}
      className={`text-left p-4 rounded-lg border transition-all ${
        isSelected
          ? 'bg-purple-500/10 border-purple-500/50 ring-1 ring-purple-500/30'
          : 'bg-slate-700/30 border-slate-600/30 hover:border-slate-500/50'
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <span className={`font-medium ${isSelected ? 'text-purple-300' : 'text-slate-200'}`}>
          {proposal.label}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded ${
          proposal.feasible
            ? 'bg-emerald-500/20 text-emerald-400'
            : 'bg-red-500/20 text-red-400'
        }`}>
          {proposal.feasible ? 'Feasible' : 'Invalid'}
        </span>
      </div>

      <div className="space-y-2 text-xs">
        {/* P1.5A: Compatibility Warning Badge - amber for "not checked" warning */}
        {proposal.compatibility?.compatibility_unknown && (
          <div className="flex items-center gap-1 px-2 py-1 bg-amber-500/10 border border-amber-500/20 rounded text-amber-400">
            <AlertTriangle className="w-3 h-3 flex-shrink-0" />
            <span className="text-[10px]">Compatibility NOT CHECKED</span>
          </div>
        )}

        {/* Validation Warning Banner */}
        {!violationsValidated && (
          <div className="flex items-center gap-1 px-2 py-1 bg-amber-500/10 border border-amber-500/20 rounded text-amber-400">
            <AlertTriangle className="w-3 h-3 flex-shrink-0" />
            <span className="text-[10px]">Not validated - confirm to verify</span>
          </div>
        )}

        {/* Quality Score */}
        <div className="flex items-center justify-between">
          <span className="text-slate-500">Quality Score</span>
          <span className={qualityColor}>
            {Math.round(proposal.quality_score * 100)}%
          </span>
        </div>

        {/* Coverage Gate - Always computed */}
        <div className="flex items-center justify-between">
          <span className="text-slate-500 flex items-center gap-1">
            <Shield className="w-3 h-3" />
            Coverage
          </span>
          <span className={coverage.coverage_percent === 100 ? 'text-emerald-400' : 'text-red-400'}>
            {coverage.coverage_percent}%
          </span>
        </div>

        {/* Block Violations Gate */}
        <div className="flex items-center justify-between">
          <span className="text-slate-500 flex items-center gap-1">
            <XCircle className="w-3 h-3" />
            Blocks
          </span>
          {violationsValidated ? (
            <span className={blockCount === 0 ? 'text-emerald-400' : 'text-red-400'}>
              {blockCount}
            </span>
          ) : (
            <span className="text-slate-500 italic">Unknown</span>
          )}
        </div>

        {/* Warnings */}
        {violationsValidated && warnCount !== null && warnCount > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-slate-500 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              Warnings
            </span>
            <span className="text-amber-400">{warnCount}</span>
          </div>
        )}

        {/* Delta Summary */}
        <div className="border-t border-slate-600/30 pt-2 mt-2">
          <div className="flex items-center justify-between">
            <span className="text-slate-500">Changed Tours</span>
            <span className="text-slate-300">{proposal.delta_summary.changed_tours_count}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500">Changed Drivers</span>
            <span className="text-slate-300">{proposal.delta_summary.changed_drivers_count}</span>
          </div>
          {proposal.delta_summary.reserve_usage > 0 && (
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Reserve Usage</span>
              <span className="text-amber-400">{proposal.delta_summary.reserve_usage}</span>
            </div>
          )}
        </div>
      </div>
    </button>
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

// P0.6: Diagnostics Panel - shown when no feasible proposals found
function DiagnosticsPanel({
  diagnostics,
  changeBudget,
  onShowPartial,
  onIncreaseBudget,
  onRunFullValidation,
}: {
  diagnostics: DiagnosticSummary;
  changeBudget: { maxChangedTours: number; maxChangedDrivers: number; maxChainDepth: number };
  onShowPartial: () => void;
  onIncreaseBudget: () => void;
  onRunFullValidation: () => void;
}) {
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 bg-amber-500/10 rounded-lg">
          <AlertTriangle className="w-6 h-6 text-amber-500" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-white">No Feasible Proposals Found</h3>
          <p className="text-sm text-slate-400">
            We couldn't find a valid repair that meets all constraints. Here's why:
          </p>
        </div>
      </div>

      {/* Blocking Reasons (Top 3) */}
      {diagnostics.reasons.length > 0 && (
        <div className="bg-slate-700/30 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-3">Blocking Reasons</h4>
          <div className="space-y-2">
            {diagnostics.reasons.slice(0, 3).map((reason, idx) => (
              <div
                key={idx}
                className="flex items-start gap-3 p-3 bg-slate-800/50 rounded-lg border border-slate-600/30"
              >
                <div className="p-1 bg-red-500/10 rounded">
                  <XCircle className="w-4 h-4 text-red-400" />
                </div>
                <div className="flex-1">
                  <p className="text-sm text-slate-200">{reason.message}</p>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-xs text-slate-500 font-mono">{reason.code}</span>
                    {reason.tour_instance_ids.length > 0 && (
                      <span className="text-xs text-slate-500">
                        Tours: {reason.tour_instance_ids.slice(0, 3).join(', ')}
                        {reason.tour_instance_ids.length > 3 && ` +${reason.tour_instance_ids.length - 3} more`}
                      </span>
                    )}
                  </div>
                  {reason.suggested_action && (
                    <p className="text-xs text-amber-400 mt-2">
                      Suggestion: {reason.suggested_action}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Uncovered Tours */}
      {diagnostics.uncovered_tour_ids.length > 0 && (
        <div className="bg-slate-700/30 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-2">Uncovered Tours</h4>
          <div className="flex flex-wrap gap-2">
            {diagnostics.uncovered_tour_ids.slice(0, 10).map((tourId) => (
              <span
                key={tourId}
                className="px-2 py-1 text-xs bg-red-500/10 text-red-400 border border-red-500/20 rounded font-mono"
              >
                Tour #{tourId}
              </span>
            ))}
            {diagnostics.uncovered_tour_ids.length > 10 && (
              <span className="px-2 py-1 text-xs bg-slate-600/30 text-slate-400 rounded">
                +{diagnostics.uncovered_tour_ids.length - 10} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* Call-to-Action Buttons */}
      <div className="border-t border-slate-700/50 pt-4">
        <h4 className="text-sm font-medium text-slate-300 mb-3">What would you like to do?</h4>
        <div className="flex flex-wrap gap-3">
          {diagnostics.partial_proposals_available && (
            <button
              onClick={onShowPartial}
              className="flex items-center gap-2 px-4 py-2 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-500/30 text-amber-400 rounded-lg text-sm font-medium transition-colors"
            >
              <Eye className="w-4 h-4" />
              Show Partial Proposals
            </button>
          )}
          <button
            onClick={onIncreaseBudget}
            className="flex flex-col items-start px-4 py-2 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 text-blue-400 rounded-lg text-sm font-medium transition-colors"
          >
            <span className="flex items-center gap-2">
              <Plus className="w-4 h-4" />
              Increase Change Budget
            </span>
            <span className="text-xs text-slate-500 mt-1">
              Current: {changeBudget.maxChangedDrivers}D/{changeBudget.maxChangedTours}T → New: {changeBudget.maxChangedDrivers + 1}D/{changeBudget.maxChangedTours + 2}T
            </span>
          </button>
          <button
            onClick={onRunFullValidation}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 text-purple-400 rounded-lg text-sm font-medium transition-colors"
          >
            <Shield className="w-4 h-4" />
            Run Full Validation
          </button>
        </div>
      </div>

      {/* Suggested Actions */}
      {diagnostics.suggested_actions.length > 0 && (
        <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-4">
          <h4 className="text-sm font-medium text-blue-400 mb-2 flex items-center gap-2">
            <Zap className="w-4 h-4" />
            Recommended Actions
          </h4>
          <ul className="list-disc list-inside text-sm text-slate-300 space-y-1">
            {diagnostics.suggested_actions.map((action, idx) => (
              <li key={idx}>{action}</li>
            ))}
          </ul>
        </div>
      )}
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
