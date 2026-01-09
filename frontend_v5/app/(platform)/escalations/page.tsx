// =============================================================================
// SOLVEREIGN Platform Admin - Escalations
// =============================================================================
// Platform-wide escalation management with filtering and resolution.
// =============================================================================

'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  AlertTriangle,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  Filter,
  X,
  Clock,
  Building2,
  Building,
  MapPin,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { getResolvedByIdentifier } from '@/lib/platform-auth';
import { ResolveEscalationDialog, type ResolveData } from '@/components/platform/resolve-escalation-dialog';

interface Escalation {
  id: string;
  scope_type: 'platform' | 'org' | 'tenant' | 'site';
  scope_id: string | null;
  status: 'healthy' | 'degraded' | 'blocked';
  severity: 'S0' | 'S1' | 'S2' | 'S3';
  reason_code: string;
  reason_message: string;
  fix_steps: string[];
  runbook_link: string;
  details: Record<string, unknown>;
  started_at: string;
  ended_at: string | null;
  resolved_by: string | null;
}

interface PlatformStatus {
  overall_status: 'healthy' | 'degraded' | 'blocked';
  worst_severity: 'S0' | 'S1' | 'S2' | 'S3' | null;
  blocked_count: number;
  degraded_count: number;
  total_active: number;
}

type FilterScope = 'all' | 'platform' | 'org' | 'tenant' | 'site';
type FilterSeverity = 'all' | 'S0' | 'S1' | 'S2' | 'S3';
type FilterStatus = 'active' | 'resolved' | 'all';

// Loading fallback for Suspense boundary
function EscalationsLoading() {
  return (
    <div className="flex items-center justify-center h-64">
      <RefreshCw className="h-6 w-6 animate-spin text-[var(--sv-gray-400)]" />
    </div>
  );
}

// Wrap the main component with Suspense
export default function EscalationsPage() {
  return (
    <Suspense fallback={<EscalationsLoading />}>
      <EscalationsPageContent />
    </Suspense>
  );
}

function EscalationsPageContent() {
  const searchParams = useSearchParams();
  const orgFilter = searchParams.get('org');

  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [scopeFilter, setScopeFilter] = useState<FilterScope>('all');
  const [severityFilter, setSeverityFilter] = useState<FilterSeverity>('all');
  const [statusFilter, setStatusFilter] = useState<FilterStatus>('active');

  // Resolution state
  const [resolving, setResolving] = useState<string | null>(null);
  const [escalationToResolve, setEscalationToResolve] = useState<Escalation | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Build query params
      const params = new URLSearchParams();
      if (scopeFilter !== 'all') {
        params.set('scope_type', scopeFilter);
      }
      if (orgFilter) {
        params.set('org_code', orgFilter);
      }

      const [escalationsRes, statusRes] = await Promise.all([
        fetch(`/api/platform/escalations${params.toString() ? `?${params.toString()}` : ''}`),
        fetch('/api/platform/status'),
      ]);

      if (escalationsRes.ok) {
        let data = await escalationsRes.json();

        // Client-side filtering for severity and status
        if (severityFilter !== 'all') {
          data = data.filter((e: Escalation) => e.severity === severityFilter);
        }
        if (statusFilter === 'active') {
          data = data.filter((e: Escalation) => !e.ended_at);
        } else if (statusFilter === 'resolved') {
          data = data.filter((e: Escalation) => e.ended_at);
        }

        setEscalations(data || []);
      }

      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setPlatformStatus(statusData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [scopeFilter, severityFilter, statusFilter, orgFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Open resolve dialog
  const handleResolve = (escalation: Escalation) => {
    setResolveError(null);
    setEscalationToResolve(escalation);
  };

  // Close resolve dialog
  const handleCloseResolveDialog = () => {
    setEscalationToResolve(null);
    setResolveError(null);
  };

  // Confirm resolution from dialog
  const handleConfirmResolve = async (resolveData: ResolveData) => {
    if (!escalationToResolve) return;

    setResolving(escalationToResolve.id);
    setResolveError(null);

    try {
      const res = await fetch('/api/platform/escalations/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope_type: escalationToResolve.scope_type,
          scope_id: escalationToResolve.scope_id,
          reason_code: escalationToResolve.reason_code,
          resolved_by: getResolvedByIdentifier(),
          comment: resolveData.comment || undefined,
          incident_ref: resolveData.incident_ref || undefined,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const errorMessage =
          data.error?.message ||
          data.detail ||
          `Failed to resolve escalation (${res.status})`;
        throw new Error(errorMessage);
      }

      // Success - close dialog and refresh
      setEscalationToResolve(null);
      fetchData();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setResolveError(errorMessage);
      throw err; // Re-throw so dialog shows error
    } finally {
      setResolving(null);
    }
  };

  const getScopeIcon = (scopeType: string) => {
    switch (scopeType) {
      case 'platform':
        return <AlertCircle className="h-4 w-4" />;
      case 'org':
        return <Building2 className="h-4 w-4" />;
      case 'tenant':
        return <Building className="h-4 w-4" />;
      case 'site':
        return <MapPin className="h-4 w-4" />;
      default:
        return <AlertCircle className="h-4 w-4" />;
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'S0':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'S1':
        return 'bg-red-500/10 text-red-400 border-red-500/20';
      case 'S2':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      case 'S3':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
  };

  const getStatusBanner = () => {
    if (!platformStatus) return null;

    if (platformStatus.overall_status === 'healthy') {
      return (
        <div className="flex items-center gap-3 p-4 rounded-lg border bg-green-500/10 border-green-500/20">
          <CheckCircle className="h-5 w-5 text-green-400" />
          <div>
            <p className="font-medium text-green-400">Platform Healthy</p>
            <p className="text-sm text-green-400/80">All systems operating normally</p>
          </div>
        </div>
      );
    }

    return (
      <div
        className={cn(
          'flex items-center gap-3 p-4 rounded-lg border',
          platformStatus.overall_status === 'blocked'
            ? 'bg-red-500/10 border-red-500/20'
            : 'bg-yellow-500/10 border-yellow-500/20'
        )}
      >
        <AlertTriangle
          className={cn(
            'h-5 w-5',
            platformStatus.overall_status === 'blocked' ? 'text-red-400' : 'text-yellow-400'
          )}
        />
        <div className="flex-1">
          <p
            className={cn(
              'font-medium',
              platformStatus.overall_status === 'blocked' ? 'text-red-400' : 'text-yellow-400'
            )}
          >
            Platform {platformStatus.overall_status === 'blocked' ? 'Blocked' : 'Degraded'}
          </p>
          <p className="text-sm text-[var(--sv-gray-400)]">
            {platformStatus.blocked_count} blocked, {platformStatus.degraded_count} degraded,{' '}
            {platformStatus.total_active} total active
          </p>
        </div>
        {platformStatus.worst_severity && (
          <span
            className={cn(
              'px-2 py-1 rounded text-xs font-medium',
              getSeverityColor(platformStatus.worst_severity)
            )}
          >
            Worst: {platformStatus.worst_severity}
          </span>
        )}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-6 w-6 animate-spin text-[var(--sv-gray-400)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Escalations</h1>
          <p className="text-sm text-[var(--sv-gray-400)] mt-1">
            Monitor and resolve platform-wide escalations
          </p>
        </div>
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

      {/* Status Banner */}
      {getStatusBanner()}

      {/* Organization Filter Notice */}
      {orgFilter && (
        <div className="flex items-center gap-2 text-sm text-[var(--sv-gray-400)]">
          <Filter className="h-4 w-4" />
          Filtered by organization: <span className="font-medium text-white">{orgFilter}</span>
          <Link
            href="/platform/escalations"
            className="text-[var(--sv-primary)] hover:underline ml-2"
          >
            Clear filter
          </Link>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 p-4 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-[var(--sv-gray-400)]" />
          <span className="text-sm text-[var(--sv-gray-400)]">Filters:</span>
        </div>

        {/* Scope Filter */}
        <select
          value={scopeFilter}
          onChange={(e) => setScopeFilter(e.target.value as FilterScope)}
          className={cn(
            'px-3 py-1.5 rounded-lg text-sm',
            'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
            'text-white',
            'focus:outline-none focus:border-[var(--sv-primary)]'
          )}
        >
          <option value="all">All Scopes</option>
          <option value="platform">Platform</option>
          <option value="org">Organization</option>
          <option value="tenant">Tenant</option>
          <option value="site">Site</option>
        </select>

        {/* Severity Filter */}
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value as FilterSeverity)}
          className={cn(
            'px-3 py-1.5 rounded-lg text-sm',
            'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
            'text-white',
            'focus:outline-none focus:border-[var(--sv-primary)]'
          )}
        >
          <option value="all">All Severities</option>
          <option value="S0">S0 - Critical</option>
          <option value="S1">S1 - High</option>
          <option value="S2">S2 - Medium</option>
          <option value="S3">S3 - Low</option>
        </select>

        {/* Status Filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as FilterStatus)}
          className={cn(
            'px-3 py-1.5 rounded-lg text-sm',
            'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-600)]',
            'text-white',
            'focus:outline-none focus:border-[var(--sv-primary)]'
          )}
        >
          <option value="active">Active Only</option>
          <option value="resolved">Resolved Only</option>
          <option value="all">All</option>
        </select>

        {/* Clear Filters */}
        {(scopeFilter !== 'all' || severityFilter !== 'all' || statusFilter !== 'active') && (
          <button
            onClick={() => {
              setScopeFilter('all');
              setSeverityFilter('all');
              setStatusFilter('active');
            }}
            className="flex items-center gap-1 text-sm text-[var(--sv-gray-400)] hover:text-white"
          >
            <X className="h-4 w-4" />
            Clear
          </button>
        )}
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

      {/* Escalations List */}
      {escalations.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 bg-[var(--sv-gray-900)] rounded-lg border border-[var(--sv-gray-700)]">
          <CheckCircle className="h-12 w-12 text-green-400 mb-4" />
          <h2 className="text-lg font-medium text-white mb-2">No escalations found</h2>
          <p className="text-sm text-[var(--sv-gray-400)] text-center max-w-md">
            {statusFilter === 'active'
              ? 'There are no active escalations matching your filters.'
              : 'No escalations match your current filters.'}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {escalations.map((escalation) => (
            <EscalationCard
              key={escalation.id}
              escalation={escalation}
              onResolve={() => handleResolve(escalation)}
              resolving={resolving === escalation.id}
              getScopeIcon={getScopeIcon}
              getSeverityColor={getSeverityColor}
            />
          ))}
        </div>
      )}

      {/* Global Resolve Error Toast */}
      {resolveError && !escalationToResolve && (
        <div className="fixed bottom-4 right-4 z-50 p-4 bg-red-500/20 border border-red-500/30 rounded-lg shadow-lg max-w-md">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-red-400">Resolution Failed</p>
              <p className="text-sm text-red-300/80 mt-1">{resolveError}</p>
            </div>
            <button
              onClick={() => setResolveError(null)}
              className="text-red-400 hover:text-red-300"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Resolve Escalation Dialog */}
      {escalationToResolve && (
        <ResolveEscalationDialog
          escalation={escalationToResolve}
          onClose={handleCloseResolveDialog}
          onConfirm={handleConfirmResolve}
        />
      )}
    </div>
  );
}

// =============================================================================
// Escalation Card Component
// =============================================================================

interface EscalationCardProps {
  escalation: Escalation;
  onResolve: () => void;
  resolving: boolean;
  getScopeIcon: (scopeType: string) => React.ReactNode;
  getSeverityColor: (severity: string) => string;
}

function EscalationCard({
  escalation,
  onResolve,
  resolving,
  getScopeIcon,
  getSeverityColor,
}: EscalationCardProps) {
  const [expanded, setExpanded] = useState(false);
  const isResolved = !!escalation.ended_at;

  return (
    <div
      className={cn(
        'rounded-lg border overflow-hidden',
        isResolved
          ? 'bg-[var(--sv-gray-900)] border-[var(--sv-gray-700)] opacity-60'
          : escalation.severity === 'S0' || escalation.severity === 'S1'
          ? 'bg-red-500/5 border-red-500/20'
          : escalation.severity === 'S2'
          ? 'bg-yellow-500/5 border-yellow-500/20'
          : 'bg-[var(--sv-gray-900)] border-[var(--sv-gray-700)]'
      )}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 flex-1">
            <div
              className={cn(
                'h-10 w-10 rounded-lg flex items-center justify-center flex-shrink-0',
                isResolved
                  ? 'bg-green-500/10'
                  : escalation.severity === 'S0' || escalation.severity === 'S1'
                  ? 'bg-red-500/10'
                  : escalation.severity === 'S2'
                  ? 'bg-yellow-500/10'
                  : 'bg-blue-500/10'
              )}
            >
              {isResolved ? (
                <CheckCircle className="h-5 w-5 text-green-400" />
              ) : (
                <AlertTriangle
                  className={cn(
                    'h-5 w-5',
                    escalation.severity === 'S0' || escalation.severity === 'S1'
                      ? 'text-red-400'
                      : escalation.severity === 'S2'
                      ? 'text-yellow-400'
                      : 'text-blue-400'
                  )}
                />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <span
                  className={cn(
                    'px-2 py-0.5 rounded text-xs font-medium border',
                    getSeverityColor(escalation.severity)
                  )}
                >
                  {escalation.severity}
                </span>
                <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]">
                  {getScopeIcon(escalation.scope_type)}
                  {escalation.scope_type}
                </span>
                <span className="text-xs font-mono text-[var(--sv-gray-400)]">
                  {escalation.reason_code}
                </span>
              </div>
              <p className="text-white font-medium">{escalation.reason_message}</p>
              <div className="flex items-center gap-4 mt-2 text-xs text-[var(--sv-gray-400)]">
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Started {new Date(escalation.started_at).toLocaleString()}
                </span>
                {isResolved && escalation.ended_at && (
                  <span className="text-green-400">
                    Resolved {new Date(escalation.ended_at).toLocaleString()}
                    {escalation.resolved_by && ` by ${escalation.resolved_by}`}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {!isResolved && (
              <button
                onClick={onResolve}
                disabled={resolving}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-sm font-medium',
                  'bg-green-500/10 text-green-400 border border-green-500/20',
                  'hover:bg-green-500/20 transition-colors',
                  'disabled:opacity-50'
                )}
              >
                {resolving ? 'Resolving...' : 'Resolve'}
              </button>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              className={cn(
                'px-3 py-1.5 rounded-lg text-sm',
                'bg-[var(--sv-gray-800)] text-[var(--sv-gray-300)]',
                'hover:bg-[var(--sv-gray-700)] transition-colors'
              )}
            >
              {expanded ? 'Less' : 'Details'}
            </button>
          </div>
        </div>
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-[var(--sv-gray-700)] p-4 bg-[var(--sv-gray-800)]/50">
          {/* Fix Steps */}
          {escalation.fix_steps && escalation.fix_steps.length > 0 && (
            <div className="mb-4">
              <p className="text-sm font-medium text-[var(--sv-gray-300)] mb-2">Fix Steps:</p>
              <ol className="text-sm text-[var(--sv-gray-400)] list-decimal list-inside space-y-1">
                {escalation.fix_steps.map((step, idx) => (
                  <li key={idx}>{step}</li>
                ))}
              </ol>
            </div>
          )}

          {/* Runbook Link */}
          {escalation.runbook_link && (
            <div className="mb-4">
              <p className="text-sm font-medium text-[var(--sv-gray-300)] mb-1">Runbook:</p>
              <a
                href={escalation.runbook_link}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-[var(--sv-primary)] hover:underline"
              >
                {escalation.runbook_link}
              </a>
            </div>
          )}

          {/* Details */}
          {escalation.details && Object.keys(escalation.details).length > 0 && (
            <div>
              <p className="text-sm font-medium text-[var(--sv-gray-300)] mb-2">
                Additional Details:
              </p>
              <pre className="text-xs text-[var(--sv-gray-400)] bg-[var(--sv-gray-900)] rounded p-3 overflow-x-auto">
                {JSON.stringify(escalation.details, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
