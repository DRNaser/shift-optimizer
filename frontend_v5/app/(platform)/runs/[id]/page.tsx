// =============================================================================
// SOLVEREIGN Platform Admin - Run Detail
// =============================================================================
// Detailed view of a solver run with audit results, KPIs, and actions.
// Actions: Publish, Lock, Request Repair
// =============================================================================

'use client';

import { useState, useEffect, useCallback, Suspense, use } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  RefreshCw,
  ArrowLeft,
  Clock,
  Users,
  Timer,
  Download,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Shield,
  ShieldOff,
  FileText,
  Hash,
  Calendar,
  Target,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  RunStatusBadge,
  PublishStateBadge,
  KillSwitchBadge,
  type RunStatus,
  type RunPublishState,
} from '@/components/ui/run-status-badge';
import { usePlatformUser } from '../../layout-client';

// =============================================================================
// TYPES
// =============================================================================

interface AuditCheck {
  name: string;
  status: 'PASS' | 'WARN' | 'FAIL';
  violation_count: number;
  details?: string;
}

interface RunKPIs {
  total_drivers: number;
  fte_count: number;
  pt_count: number;
  coverage_pct: number;
  total_tours: number;
  assigned_tours: number;
  unassigned_tours: number;
  max_weekly_hours: number;
  avg_weekly_hours: number;
}

interface RunDetail {
  run_id: string;
  week_id: string;
  status: RunStatus;
  publish_state: RunPublishState;
  created_at: string;
  published_at?: string;
  locked_at?: string;
  published_by?: string;
  locked_by?: string;
  evidence_hash?: string;
  solver_seed: number;
  runtime_seconds: number;
  kpis: RunKPIs;
  audits: AuditCheck[];
  can_publish: boolean;
  can_lock: boolean;
  publish_blocked_reason?: string;
  lock_blocked_reason?: string;
}

interface SystemStatus {
  kill_switch_active: boolean;
  publish_enabled: boolean;
  lock_enabled: boolean;
  site_enabled: boolean;
}

// =============================================================================
// LOADING FALLBACK
// =============================================================================

function RunDetailLoading() {
  return (
    <div className="flex items-center justify-center h-64">
      <RefreshCw className="h-6 w-6 animate-spin text-[var(--sv-gray-400)]" />
    </div>
  );
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);

  return (
    <Suspense fallback={<RunDetailLoading />}>
      <RunDetailContent runId={resolvedParams.id} />
    </Suspense>
  );
}

function RunDetailContent({ runId }: { runId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = usePlatformUser();

  // Get tenant/site from query params
  const tenantCode = searchParams.get('tenant') || 'lts';
  const siteCode = searchParams.get('site') || 'wien';

  // State
  const [run, setRun] = useState<RunDetail | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Action state
  const [publishing, setPublishing] = useState(false);
  const [locking, setLocking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [showLockModal, setShowLockModal] = useState(false);
  const [showRepairForm, setShowRepairForm] = useState(false);

  // Fetch data
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [runRes, statusRes] = await Promise.all([
        fetch(`/api/platform/dispatcher/runs/${runId}?tenant=${tenantCode}&site=${siteCode}`),
        fetch(`/api/platform/dispatcher/status?tenant=${tenantCode}&site=${siteCode}`),
      ]);

      if (runRes.ok) {
        const data = await runRes.json();
        setRun(data);
      } else {
        const errData = await runRes.json().catch(() => ({}));
        throw new Error(errData.message || `Failed to fetch run (${runRes.status})`);
      }

      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setSystemStatus(statusData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [runId, tenantCode, siteCode]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Publish action
  const handlePublish = async (reason: string) => {
    if (!run) return;

    setPublishing(true);
    setActionError(null);

    try {
      const res = await fetch(
        `/api/platform/dispatcher/runs/${runId}/publish?tenant=${tenantCode}&site=${siteCode}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            approver_id: user.email,
            approver_role: user.role as 'dispatcher' | 'ops_lead' | 'platform_admin',
            reason,
          }),
        }
      );

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || `Publish failed (${res.status})`);
      }

      // Refresh data
      setShowPublishModal(false);
      await fetchData();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Publish failed');
    } finally {
      setPublishing(false);
    }
  };

  // Lock action
  const handleLock = async (reason: string) => {
    if (!run) return;

    setLocking(true);
    setActionError(null);

    try {
      const res = await fetch(
        `/api/platform/dispatcher/runs/${runId}/lock?tenant=${tenantCode}&site=${siteCode}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            approver_id: user.email,
            approver_role: user.role as 'dispatcher' | 'ops_lead' | 'platform_admin',
            reason,
          }),
        }
      );

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || `Lock failed (${res.status})`);
      }

      // Refresh data
      setShowLockModal(false);
      await fetchData();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Lock failed');
    } finally {
      setLocking(false);
    }
  };

  // Format helpers
  const formatRuntime = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return <RunDetailLoading />;
  }

  if (error || !run) {
    return (
      <div className="space-y-6">
        <Link
          href="/runs"
          className="inline-flex items-center gap-2 text-sm text-[var(--sv-gray-400)] hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Runs
        </Link>
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-6 text-center">
          <p className="text-red-400">{error || 'Run not found'}</p>
          <button
            onClick={fetchData}
            className="mt-4 text-sm text-red-400 hover:text-red-300"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const killSwitchActive = systemStatus?.kill_switch_active || false;

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href="/runs"
        className="inline-flex items-center gap-2 text-sm text-[var(--sv-gray-400)] hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Runs
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-2xl font-semibold text-white font-mono">
              {run.run_id.slice(0, 12)}...
            </h1>
            <RunStatusBadge status={run.status} size="lg" />
            <PublishStateBadge state={run.publish_state} size="lg" />
          </div>
          <p className="text-sm text-[var(--sv-gray-400)]">
            Week {run.week_id} &bull; Created {formatDate(run.created_at)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <KillSwitchBadge active={killSwitchActive} />
          <button
            onClick={fetchData}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-lg text-sm',
              'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
              'hover:bg-[var(--sv-gray-700)] transition-colors'
            )}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Action Error */}
      {actionError && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-medium text-red-400">Action Failed</p>
            <p className="text-sm text-red-300/80">{actionError}</p>
          </div>
          <button
            onClick={() => setActionError(null)}
            className="text-red-400 hover:text-red-300"
          >
            <XCircle className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* KPIs Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          icon={Users}
          label="Total Drivers"
          value={run.kpis.total_drivers.toString()}
          subValue={
            run.kpis.pt_count > 0
              ? `${run.kpis.fte_count} FTE, ${run.kpis.pt_count} PT`
              : `${run.kpis.fte_count} FTE`
          }
          highlight={run.kpis.pt_count === 0}
        />
        <KPICard
          icon={Target}
          label="Coverage"
          value={`${run.kpis.coverage_pct.toFixed(1)}%`}
          subValue={`${run.kpis.assigned_tours}/${run.kpis.total_tours} tours`}
          highlight={run.kpis.coverage_pct === 100}
        />
        <KPICard
          icon={Timer}
          label="Runtime"
          value={formatRuntime(run.runtime_seconds)}
          subValue={`Seed ${run.solver_seed}`}
        />
        <KPICard
          icon={Calendar}
          label="Max Hours"
          value={`${run.kpis.max_weekly_hours.toFixed(1)}h`}
          subValue={`Avg ${run.kpis.avg_weekly_hours.toFixed(1)}h`}
          highlight={run.kpis.max_weekly_hours <= 55}
        />
      </div>

      {/* Audits Section */}
      <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--sv-gray-700)]">
          <h2 className="text-lg font-medium text-white">Audit Results</h2>
          <p className="text-sm text-[var(--sv-gray-400)]">
            {run.audits.filter((a) => a.status === 'PASS').length}/{run.audits.length} checks passed
          </p>
        </div>
        <div className="divide-y divide-[var(--sv-gray-700)]">
          {run.audits.map((audit) => (
            <AuditRow key={audit.name} audit={audit} />
          ))}
        </div>
      </div>

      {/* Evidence Section */}
      {run.evidence_hash && (
        <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Hash className="h-5 w-5 text-[var(--sv-gray-400)]" />
              <div>
                <p className="text-sm font-medium text-white">Evidence Hash</p>
                <p className="text-xs font-mono text-[var(--sv-gray-400)]">
                  {run.evidence_hash}
                </p>
              </div>
            </div>
            <button
              className={cn(
                'flex items-center gap-2 px-3 py-2 rounded-lg text-sm',
                'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                'hover:bg-[var(--sv-gray-700)] transition-colors'
              )}
            >
              <Download className="h-4 w-4" />
              Download Evidence
            </button>
          </div>
        </div>
      )}

      {/* Actions Section */}
      <div className="bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] p-4">
        <h2 className="text-lg font-medium text-white mb-4">Actions</h2>
        <div className="flex flex-wrap gap-3">
          {/* Publish Button */}
          {run.publish_state === 'draft' && (
            <button
              onClick={() => setShowPublishModal(true)}
              disabled={!run.can_publish || killSwitchActive || publishing}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
                run.can_publish && !killSwitchActive
                  ? 'bg-blue-500 text-white hover:bg-blue-600'
                  : 'bg-[var(--sv-gray-700)] text-[var(--sv-gray-500)] cursor-not-allowed',
                'transition-colors'
              )}
            >
              <Shield className="h-4 w-4" />
              {publishing ? 'Publishing...' : 'Publish Run'}
            </button>
          )}

          {/* Lock Button */}
          {run.publish_state === 'published' && (
            <button
              onClick={() => setShowLockModal(true)}
              disabled={!run.can_lock || killSwitchActive || locking}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
                run.can_lock && !killSwitchActive
                  ? 'bg-purple-500 text-white hover:bg-purple-600'
                  : 'bg-[var(--sv-gray-700)] text-[var(--sv-gray-500)] cursor-not-allowed',
                'transition-colors'
              )}
            >
              <ShieldOff className="h-4 w-4" />
              {locking ? 'Locking...' : 'Lock Run'}
            </button>
          )}

          {/* Repair Request Button */}
          <button
            onClick={() => setShowRepairForm(true)}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
              'bg-yellow-500/10 text-yellow-400 border border-yellow-500/30',
              'hover:bg-yellow-500/20 transition-colors'
            )}
          >
            <FileText className="h-4 w-4" />
            Request Repair
          </button>

          {/* Blocked Reasons */}
          {run.publish_blocked_reason && run.publish_state === 'draft' && (
            <p className="w-full text-sm text-red-400 mt-2">
              {run.publish_blocked_reason}
            </p>
          )}
          {run.lock_blocked_reason && run.publish_state === 'published' && (
            <p className="w-full text-sm text-red-400 mt-2">
              {run.lock_blocked_reason}
            </p>
          )}
        </div>

        {/* Publish/Lock Info */}
        {run.published_at && (
          <p className="text-sm text-[var(--sv-gray-400)] mt-4">
            Published {formatDate(run.published_at)}
            {run.published_by && ` by ${run.published_by}`}
          </p>
        )}
        {run.locked_at && (
          <p className="text-sm text-[var(--sv-gray-400)] mt-1">
            Locked {formatDate(run.locked_at)}
            {run.locked_by && ` by ${run.locked_by}`}
          </p>
        )}
      </div>

      {/* Publish Modal */}
      {showPublishModal && (
        <ApprovalModal
          title="Publish Run"
          description="Publishing this run will make it the active schedule for this site."
          icon={Shield}
          iconColor="text-blue-400"
          confirmLabel={publishing ? 'Publishing...' : 'Publish'}
          onConfirm={handlePublish}
          onCancel={() => setShowPublishModal(false)}
          loading={publishing}
        />
      )}

      {/* Lock Modal */}
      {showLockModal && (
        <ApprovalModal
          title="Lock Run"
          description="Locking this run will make it immutable and ready for export."
          icon={ShieldOff}
          iconColor="text-purple-400"
          confirmLabel={locking ? 'Locking...' : 'Lock'}
          onConfirm={handleLock}
          onCancel={() => setShowLockModal(false)}
          loading={locking}
        />
      )}

      {/* Repair Form Modal */}
      {showRepairForm && (
        <RepairRequestModal
          runId={runId}
          tenantCode={tenantCode}
          siteCode={siteCode}
          onClose={() => setShowRepairForm(false)}
          onSuccess={() => {
            setShowRepairForm(false);
            fetchData();
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// KPI CARD
// =============================================================================

interface KPICardProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  subValue?: string;
  highlight?: boolean;
}

function KPICard({ icon: Icon, label, value, subValue, highlight }: KPICardProps) {
  return (
    <div
      className={cn(
        'bg-[var(--sv-gray-900)] rounded-lg border p-4',
        highlight
          ? 'border-green-500/30 bg-green-500/5'
          : 'border-[var(--sv-gray-700)]'
      )}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon
          className={cn('h-4 w-4', highlight ? 'text-green-400' : 'text-[var(--sv-gray-400)]')}
        />
        <span className="text-sm text-[var(--sv-gray-400)]">{label}</span>
      </div>
      <p className={cn('text-2xl font-semibold', highlight ? 'text-green-400' : 'text-white')}>
        {value}
      </p>
      {subValue && <p className="text-xs text-[var(--sv-gray-500)] mt-1">{subValue}</p>}
    </div>
  );
}

// =============================================================================
// AUDIT ROW
// =============================================================================

interface AuditRowProps {
  audit: AuditCheck;
}

function AuditRow({ audit }: AuditRowProps) {
  const statusConfig = {
    PASS: { icon: CheckCircle, color: 'text-green-400' },
    WARN: { icon: AlertTriangle, color: 'text-yellow-400' },
    FAIL: { icon: XCircle, color: 'text-red-400' },
  };

  const config = statusConfig[audit.status];
  const Icon = config.icon;

  return (
    <div className="flex items-center justify-between px-4 py-3">
      <div className="flex items-center gap-3">
        <Icon className={cn('h-5 w-5', config.color)} />
        <div>
          <p className="text-sm font-medium text-white">{audit.name}</p>
          {audit.details && (
            <p className="text-xs text-[var(--sv-gray-400)]">{audit.details}</p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-3">
        {audit.violation_count > 0 && (
          <span className="text-xs text-[var(--sv-gray-400)]">
            {audit.violation_count} violation{audit.violation_count !== 1 ? 's' : ''}
          </span>
        )}
        <span
          className={cn(
            'px-2 py-0.5 rounded text-xs font-medium',
            audit.status === 'PASS' && 'bg-green-500/10 text-green-400',
            audit.status === 'WARN' && 'bg-yellow-500/10 text-yellow-400',
            audit.status === 'FAIL' && 'bg-red-500/10 text-red-400'
          )}
        >
          {audit.status}
        </span>
      </div>
    </div>
  );
}

// =============================================================================
// APPROVAL MODAL
// =============================================================================

interface ApprovalModalProps {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
  confirmLabel: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  loading?: boolean;
}

function ApprovalModal({
  title,
  description,
  icon: Icon,
  iconColor,
  confirmLabel,
  onConfirm,
  onCancel,
  loading,
}: ApprovalModalProps) {
  const [reason, setReason] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (reason.length >= 10) {
      onConfirm(reason);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onCancel} />

      {/* Modal */}
      <div className="relative bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] w-full max-w-md mx-4 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center', 'bg-[var(--sv-gray-800)]')}>
            <Icon className={cn('h-5 w-5', iconColor)} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">{title}</h3>
            <p className="text-sm text-[var(--sv-gray-400)]">{description}</p>
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-2">
              Approval Reason <span className="text-red-400">*</span>
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Enter reason for approval (min 10 characters)..."
              rows={3}
              className={cn(
                'w-full px-3 py-2 rounded-lg text-sm',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder:text-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            />
            {reason.length > 0 && reason.length < 10 && (
              <p className="text-xs text-red-400 mt-1">
                Reason must be at least 10 characters
              </p>
            )}
          </div>

          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onCancel}
              disabled={loading}
              className={cn(
                'px-4 py-2 rounded-lg text-sm',
                'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                'hover:bg-[var(--sv-gray-700)] transition-colors'
              )}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={reason.length < 10 || loading}
              className={cn(
                'px-4 py-2 rounded-lg text-sm font-medium',
                reason.length >= 10 && !loading
                  ? 'bg-[var(--sv-primary)] text-white hover:bg-[var(--sv-primary-dark)]'
                  : 'bg-[var(--sv-gray-700)] text-[var(--sv-gray-500)] cursor-not-allowed',
                'transition-colors'
              )}
            >
              {confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// =============================================================================
// REPAIR REQUEST MODAL
// =============================================================================

interface RepairRequestModalProps {
  runId: string;
  tenantCode: string;
  siteCode: string;
  onClose: () => void;
  onSuccess: () => void;
}

function RepairRequestModal({
  runId,
  tenantCode,
  siteCode,
  onClose,
  onSuccess,
}: RepairRequestModalProps) {
  const [driverId, setDriverId] = useState('');
  const [driverName, setDriverName] = useState('');
  const [absenceType, setAbsenceType] = useState<'sick' | 'vacation' | 'no_show'>('sick');
  const [affectedTours, setAffectedTours] = useState('');
  const [urgency, setUrgency] = useState<'critical' | 'high' | 'normal'>('normal');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const tours = affectedTours.split(',').map((t) => t.trim()).filter(Boolean);

      const res = await fetch(
        `/api/platform/dispatcher/runs/${runId}/repair?tenant=${tenantCode}&site=${siteCode}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            driver_id: driverId,
            driver_name: driverName,
            absence_type: absenceType,
            affected_tours: tours,
            urgency,
            notes: notes || undefined,
          }),
        }
      );

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || `Request failed (${res.status})`);
      }

      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setSubmitting(false);
    }
  };

  const isValid = driverId && driverName && affectedTours;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)] w-full max-w-lg mx-4 p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center gap-3 mb-4">
          <div className="h-10 w-10 rounded-lg flex items-center justify-center bg-yellow-500/10">
            <FileText className="h-5 w-5 text-yellow-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Request Repair</h3>
            <p className="text-sm text-[var(--sv-gray-400)]">
              Submit a sick-call or no-show repair request
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Driver ID <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={driverId}
                onChange={(e) => setDriverId(e.target.value)}
                placeholder="e.g., D001"
                className={cn(
                  'w-full px-3 py-2 rounded-lg text-sm',
                  'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                  'text-white placeholder:text-[var(--sv-gray-500)]',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Driver Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={driverName}
                onChange={(e) => setDriverName(e.target.value)}
                placeholder="e.g., Max Mustermann"
                className={cn(
                  'w-full px-3 py-2 rounded-lg text-sm',
                  'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                  'text-white placeholder:text-[var(--sv-gray-500)]',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Absence Type <span className="text-red-400">*</span>
              </label>
              <select
                value={absenceType}
                onChange={(e) => setAbsenceType(e.target.value as typeof absenceType)}
                className={cn(
                  'w-full px-3 py-2 rounded-lg text-sm',
                  'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                  'text-white',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
              >
                <option value="sick">Sick Call</option>
                <option value="vacation">Vacation</option>
                <option value="no_show">No Show</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Urgency
              </label>
              <select
                value={urgency}
                onChange={(e) => setUrgency(e.target.value as typeof urgency)}
                className={cn(
                  'w-full px-3 py-2 rounded-lg text-sm',
                  'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                  'text-white',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
              >
                <option value="normal">Normal</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Affected Tours <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={affectedTours}
              onChange={(e) => setAffectedTours(e.target.value)}
              placeholder="e.g., T001, T002, T003"
              className={cn(
                'w-full px-3 py-2 rounded-lg text-sm',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder:text-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            />
            <p className="text-xs text-[var(--sv-gray-500)] mt-1">
              Comma-separated list of tour IDs
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
              Notes
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Additional information..."
              rows={2}
              className={cn(
                'w-full px-3 py-2 rounded-lg text-sm',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
                'text-white placeholder:text-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className={cn(
                'px-4 py-2 rounded-lg text-sm',
                'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                'hover:bg-[var(--sv-gray-700)] transition-colors'
              )}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!isValid || submitting}
              className={cn(
                'px-4 py-2 rounded-lg text-sm font-medium',
                isValid && !submitting
                  ? 'bg-yellow-500 text-black hover:bg-yellow-400'
                  : 'bg-[var(--sv-gray-700)] text-[var(--sv-gray-500)] cursor-not-allowed',
                'transition-colors'
              )}
            >
              {submitting ? 'Submitting...' : 'Submit Request'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
