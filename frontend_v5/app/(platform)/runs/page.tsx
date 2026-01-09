// =============================================================================
// SOLVEREIGN Platform Admin - Dispatcher Runs
// =============================================================================
// List solver runs with status, audits, and KPIs.
// Wien-only filter by default. Supports publish/lock actions.
// =============================================================================

'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  RefreshCw,
  Filter,
  X,
  Clock,
  Users,
  Timer,
  ChevronRight,
  MapPin,
  AlertTriangle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  RunStatusBadge,
  PublishStateBadge,
  KillSwitchBadge,
  AuditCheckBadge,
  type RunStatus,
  type RunPublishState,
} from '@/components/ui/run-status-badge';

// =============================================================================
// TYPES
// =============================================================================

interface RunSummary {
  run_id: string;
  week_id: string;
  status: RunStatus;
  publish_state: RunPublishState;
  headcount: number;
  fte_count: number;
  pt_count: number;
  coverage_pct: number;
  runtime_seconds: number;
  audits_passed: number;
  audits_total: number;
  created_at: string;
  evidence_hash?: string;
}

interface SystemStatus {
  kill_switch_active: boolean;
  publish_enabled: boolean;
  lock_enabled: boolean;
  site_enabled: boolean;
  pending_repairs: number;
  latest_run_id?: string;
}

type StatusFilter = 'all' | 'PASS' | 'WARN' | 'FAIL' | 'BLOCKED' | 'PENDING';

// =============================================================================
// LOADING FALLBACK
// =============================================================================

function RunsLoading() {
  return (
    <div className="flex items-center justify-center h-64">
      <RefreshCw className="h-6 w-6 animate-spin text-[var(--sv-gray-400)]" />
    </div>
  );
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function RunsPage() {
  return (
    <Suspense fallback={<RunsLoading />}>
      <RunsPageContent />
    </Suspense>
  );
}

function RunsPageContent() {
  const router = useRouter();

  // State
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters - Default to Wien site
  const [tenantCode] = useState('lts');
  const [siteCode] = useState('wien');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  // Fetch data
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Build query params
      const params = new URLSearchParams();
      params.set('tenant', tenantCode);
      params.set('site', siteCode);
      params.set('limit', '50');
      if (statusFilter !== 'all') {
        params.set('status', statusFilter);
      }

      // Fetch runs and system status in parallel
      const [runsRes, statusRes] = await Promise.all([
        fetch(`/api/platform/dispatcher/runs?${params.toString()}`),
        fetch(`/api/platform/dispatcher/status?tenant=${tenantCode}&site=${siteCode}`),
      ]);

      if (runsRes.ok) {
        const data = await runsRes.json();
        setRuns(data.runs || []);
      } else {
        const errData = await runsRes.json().catch(() => ({}));
        throw new Error(errData.message || `Failed to fetch runs (${runsRes.status})`);
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
  }, [tenantCode, siteCode, statusFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Navigate to run detail
  const handleRunClick = (runId: string) => {
    router.push(`/runs/${runId}?tenant=${tenantCode}&site=${siteCode}`);
  };

  // Format runtime
  const formatRuntime = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  // Format date
  const formatDate = (dateStr: string): string => {
    const date = new Date(dateStr);
    return date.toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // Status banner
  const getStatusBanner = () => {
    if (!systemStatus) return null;

    if (systemStatus.kill_switch_active) {
      return (
        <div className="flex items-center gap-3 p-4 rounded-lg border bg-red-500/10 border-red-500/20">
          <AlertTriangle className="h-5 w-5 text-red-400" />
          <div className="flex-1">
            <p className="font-medium text-red-400">Kill Switch Active</p>
            <p className="text-sm text-red-400/80">
              All publish and lock operations are disabled platform-wide.
            </p>
          </div>
          <KillSwitchBadge active={true} />
        </div>
      );
    }

    if (!systemStatus.site_enabled) {
      return (
        <div className="flex items-center gap-3 p-4 rounded-lg border bg-yellow-500/10 border-yellow-500/20">
          <AlertTriangle className="h-5 w-5 text-yellow-400" />
          <div>
            <p className="font-medium text-yellow-400">Site Not Enabled</p>
            <p className="text-sm text-yellow-400/80">
              Wien site is not enabled for publish/lock operations.
            </p>
          </div>
        </div>
      );
    }

    if (systemStatus.pending_repairs > 0) {
      return (
        <div className="flex items-center gap-3 p-4 rounded-lg border bg-yellow-500/10 border-yellow-500/20">
          <AlertTriangle className="h-5 w-5 text-yellow-400" />
          <div>
            <p className="font-medium text-yellow-400">
              {systemStatus.pending_repairs} Pending Repair Request{systemStatus.pending_repairs > 1 ? 's' : ''}
            </p>
            <p className="text-sm text-yellow-400/80">
              Review repair requests before publishing.
            </p>
          </div>
        </div>
      );
    }

    return null;
  };

  if (loading) {
    return <RunsLoading />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Solver Runs</h1>
          <p className="text-sm text-[var(--sv-gray-400)] mt-1 flex items-center gap-2">
            <MapPin className="h-4 w-4" />
            Wien Site &bull; LTS Tenant
          </p>
        </div>
        <div className="flex items-center gap-3">
          {systemStatus && (
            <KillSwitchBadge active={systemStatus.kill_switch_active} size="lg" />
          )}
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

      {/* Status Banner */}
      {getStatusBanner()}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 p-4 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-[var(--sv-gray-400)]" />
          <span className="text-sm text-[var(--sv-gray-400)]">Filter:</span>
        </div>

        {/* Status Filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          className={cn(
            'px-3 py-1.5 rounded-lg text-sm',
            'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
            'text-white',
            'focus:outline-none focus:border-[var(--sv-primary)]'
          )}
        >
          <option value="all">All Status</option>
          <option value="PASS">Pass</option>
          <option value="WARN">Warn</option>
          <option value="FAIL">Fail</option>
          <option value="BLOCKED">Blocked</option>
          <option value="PENDING">Pending</option>
        </select>

        {/* Clear Filters */}
        {statusFilter !== 'all' && (
          <button
            onClick={() => setStatusFilter('all')}
            className="flex items-center gap-1 text-sm text-[var(--sv-gray-400)] hover:text-white"
          >
            <X className="h-4 w-4" />
            Clear
          </button>
        )}

        {/* Results count */}
        <span className="text-sm text-[var(--sv-gray-400)] ml-auto">
          {runs.length} run{runs.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
          <p className="text-red-400">{error}</p>
          <button
            onClick={fetchData}
            className="mt-2 text-sm text-red-400 hover:text-red-300"
          >
            Retry
          </button>
        </div>
      )}

      {/* Runs List */}
      {runs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
          <Clock className="h-12 w-12 text-[var(--sv-gray-500)] mb-4" />
          <h2 className="text-lg font-medium text-white mb-2">No runs found</h2>
          <p className="text-sm text-[var(--sv-gray-400)] text-center max-w-md">
            {statusFilter !== 'all'
              ? 'No runs match your current filter.'
              : 'No solver runs have been executed for this site yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <RunCard
              key={run.run_id}
              run={run}
              onClick={() => handleRunClick(run.run_id)}
              formatRuntime={formatRuntime}
              formatDate={formatDate}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// RUN CARD COMPONENT
// =============================================================================

interface RunCardProps {
  run: RunSummary;
  onClick: () => void;
  formatRuntime: (seconds: number) => string;
  formatDate: (dateStr: string) => string;
}

function RunCard({ run, onClick, formatRuntime, formatDate }: RunCardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'rounded-lg border overflow-hidden cursor-pointer',
        'bg-[var(--sv-gray-900)] border-[var(--sv-gray-700)]',
        'hover:border-[var(--sv-gray-600)] hover:bg-[var(--sv-gray-800)]/50',
        'transition-colors duration-150'
      )}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-4">
          {/* Left: Run info */}
          <div className="flex-1 min-w-0">
            {/* Header row */}
            <div className="flex items-center gap-3 mb-2 flex-wrap">
              <span className="font-mono text-sm text-white font-medium">
                {run.run_id.slice(0, 8)}
              </span>
              <span className="text-sm text-[var(--sv-gray-400)]">
                Week {run.week_id}
              </span>
              <RunStatusBadge status={run.status} size="sm" />
              <PublishStateBadge state={run.publish_state} size="sm" />
            </div>

            {/* KPIs row */}
            <div className="flex items-center gap-4 text-sm text-[var(--sv-gray-400)]">
              <span className="flex items-center gap-1.5">
                <Users className="h-4 w-4" />
                {run.headcount} drivers
                {run.pt_count > 0 && (
                  <span className="text-yellow-400">({run.pt_count} PT)</span>
                )}
              </span>
              <span className="flex items-center gap-1.5">
                <Timer className="h-4 w-4" />
                {formatRuntime(run.runtime_seconds)}
              </span>
              <AuditCheckBadge
                passed={run.audits_passed}
                total={run.audits_total}
                size="sm"
              />
              <span className="flex items-center gap-1.5">
                {run.coverage_pct.toFixed(1)}% coverage
              </span>
            </div>

            {/* Timestamp */}
            <div className="flex items-center gap-2 mt-2 text-xs text-[var(--sv-gray-500)]">
              <Clock className="h-3 w-3" />
              {formatDate(run.created_at)}
            </div>
          </div>

          {/* Right: Arrow */}
          <div className="flex items-center">
            <ChevronRight className="h-5 w-5 text-[var(--sv-gray-500)]" />
          </div>
        </div>
      </div>
    </div>
  );
}
