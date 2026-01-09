// =============================================================================
// SOLVEREIGN Tenant - Teams Daily Page
// =============================================================================
// /tenant/teams/daily
//
// 2-PERSON ENFORCEMENT (HARD GATE):
// - MISMATCH_UNDER = Stop requires 2-person but team has 1 => BLOCKS PUBLISH
// - MISMATCH_OVER = Team has 2 but stop only needs 1 => Warning only
//
// Flow:
// 1. Select date
// 2. View team assignments with demand_status
// 3. Run compliance check
// 4. If violations exist, show blocking message
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Users,
  Calendar,
  AlertTriangle,
  CheckCircle,
  XCircle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
  Shield,
  Clock,
  Truck,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTenant } from '@/lib/hooks/use-tenant';
import type { TeamDailyAssignment, Team } from '@/lib/tenant-api';

// =============================================================================
// DEMAND STATUS BADGE
// =============================================================================

type DemandStatus = 'MATCHED' | 'MISMATCH_UNDER' | 'MISMATCH_OVER' | null;

function DemandStatusBadge({ status }: { status: DemandStatus }) {
  if (!status) return null;

  const configs: Record<NonNullable<DemandStatus>, { icon: typeof CheckCircle; color: string; label: string }> = {
    MATCHED: { icon: CheckCircle, color: 'text-[var(--sv-success)] bg-[var(--sv-success-light)]', label: 'OK' },
    MISMATCH_UNDER: { icon: XCircle, color: 'text-[var(--sv-error)] bg-[var(--sv-error-light)]', label: 'Fehlt 2. Person' },
    MISMATCH_OVER: { icon: AlertTriangle, color: 'text-[var(--sv-warning)] bg-[var(--sv-warning-light)]', label: 'Ueberbesetzt' },
  };

  const { icon: Icon, color, label } = configs[status];

  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium', color)}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

// =============================================================================
// TEAM CARD
// =============================================================================

function TeamCard({ assignment }: { assignment: TeamDailyAssignment }) {
  const { team } = assignment;
  const hasViolation = assignment.demand_status === 'MISMATCH_UNDER';

  return (
    <div
      className={cn(
        'border rounded-lg p-4 bg-[var(--card)]',
        hasViolation ? 'border-[var(--sv-error)]' : 'border-[var(--border)]'
      )}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={cn(
            'p-2 rounded-lg',
            team.team_size === 2 ? 'bg-[var(--sv-primary)]/10' : 'bg-[var(--muted)]'
          )}>
            <Users className={cn(
              'h-5 w-5',
              team.team_size === 2 ? 'text-[var(--sv-primary)]' : 'text-[var(--muted-foreground)]'
            )} />
          </div>
          <div>
            <h3 className="font-medium">{team.team_code}</h3>
            <p className="text-sm text-[var(--muted-foreground)]">
              {team.team_size === 2 ? '2-Mann Team' : '1-Mann Team'}
            </p>
          </div>
        </div>
        <DemandStatusBadge status={assignment.demand_status} />
      </div>

      {/* Drivers */}
      <div className="mt-4 space-y-2">
        <div className="flex items-center gap-2 text-sm">
          <div className="h-6 w-6 rounded-full bg-[var(--sv-primary)] flex items-center justify-center text-white text-xs font-medium">
            {team.driver_1_name.charAt(0)}
          </div>
          <span>{team.driver_1_name}</span>
        </div>
        {team.driver_2_name ? (
          <div className="flex items-center gap-2 text-sm">
            <div className="h-6 w-6 rounded-full bg-[var(--sv-primary)] flex items-center justify-center text-white text-xs font-medium">
              {team.driver_2_name.charAt(0)}
            </div>
            <span>{team.driver_2_name}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <div className="h-6 w-6 rounded-full border-2 border-dashed border-[var(--border)] flex items-center justify-center">
              <span className="text-xs">?</span>
            </div>
            <span>Kein 2. Fahrer</span>
          </div>
        )}
      </div>

      {/* Shift Info */}
      <div className="mt-4 flex items-center gap-4 text-sm text-[var(--muted-foreground)]">
        <div className="flex items-center gap-1">
          <Clock className="h-4 w-4" />
          {assignment.shift_start} - {assignment.shift_end}
        </div>
        {assignment.vehicle_id && (
          <div className="flex items-center gap-1">
            <Truck className="h-4 w-4" />
            {assignment.vehicle_id}
          </div>
        )}
      </div>

      {/* Warning for 2-person requirement */}
      {assignment.requires_two_person && (
        <div className={cn(
          'mt-4 px-3 py-2 rounded-md text-sm',
          hasViolation ? 'bg-[var(--sv-error-light)] text-[var(--sv-error)]' : 'bg-[var(--sv-info-light)] text-[var(--sv-info)]'
        )}>
          {hasViolation
            ? 'Stops erfordern 2-Mann Team - Publish BLOCKIERT'
            : 'Stops erfordern 2-Mann Team - OK'}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// COMPLIANCE SUMMARY
// =============================================================================

interface ComplianceSummary {
  total_teams: number;
  matched: number;
  mismatch_under: number;
  mismatch_over: number;
  can_publish: boolean;
}

function ComplianceSummaryCard({
  summary,
  onCheckCompliance,
  isLoading,
}: {
  summary: ComplianceSummary;
  onCheckCompliance: () => void;
  isLoading: boolean;
}) {
  const hasBlockingViolations = summary.mismatch_under > 0;

  return (
    <div className={cn(
      'border rounded-lg p-6',
      hasBlockingViolations ? 'border-[var(--sv-error)] bg-[var(--sv-error-light)]' : 'border-[var(--border)] bg-[var(--card)]'
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className={cn(
            'h-6 w-6',
            hasBlockingViolations ? 'text-[var(--sv-error)]' : 'text-[var(--sv-success)]'
          )} />
          <div>
            <h2 className="font-semibold">2-Person Compliance</h2>
            <p className={cn(
              'text-sm',
              hasBlockingViolations ? 'text-[var(--sv-error)]' : 'text-[var(--muted-foreground)]'
            )}>
              {hasBlockingViolations
                ? `${summary.mismatch_under} blockierende Verstoesse - Publish NICHT moeglich`
                : 'Alle Anforderungen erfuellt - Publish erlaubt'}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onCheckCompliance}
          disabled={isLoading}
          className="flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)] disabled:opacity-50"
        >
          {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
          Pruefung starten
        </button>
      </div>

      {/* Stats */}
      <div className="mt-4 grid grid-cols-4 gap-4">
        <div className="text-center p-3 bg-white/50 rounded-md">
          <div className="text-2xl font-bold">{summary.total_teams}</div>
          <div className="text-xs text-[var(--muted-foreground)]">Teams gesamt</div>
        </div>
        <div className="text-center p-3 bg-[var(--sv-success-light)] rounded-md">
          <div className="text-2xl font-bold text-[var(--sv-success)]">{summary.matched}</div>
          <div className="text-xs text-[var(--muted-foreground)]">OK</div>
        </div>
        <div className="text-center p-3 bg-[var(--sv-error-light)] rounded-md">
          <div className="text-2xl font-bold text-[var(--sv-error)]">{summary.mismatch_under}</div>
          <div className="text-xs text-[var(--muted-foreground)]">Blockiert</div>
        </div>
        <div className="text-center p-3 bg-[var(--sv-warning-light)] rounded-md">
          <div className="text-2xl font-bold text-[var(--sv-warning)]">{summary.mismatch_over}</div>
          <div className="text-xs text-[var(--muted-foreground)]">Warnung</div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// DATE SELECTOR
// =============================================================================

function DateSelector({
  date,
  onDateChange,
}: {
  date: string;
  onDateChange: (date: string) => void;
}) {
  const goToPrevDay = () => {
    const d = new Date(date);
    d.setDate(d.getDate() - 1);
    onDateChange(d.toISOString().split('T')[0]);
  };

  const goToNextDay = () => {
    const d = new Date(date);
    d.setDate(d.getDate() + 1);
    onDateChange(d.toISOString().split('T')[0]);
  };

  const goToToday = () => {
    onDateChange(new Date().toISOString().split('T')[0]);
  };

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={goToPrevDay}
        className="p-2 border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <div className="flex items-center gap-2 px-3 py-2 border border-[var(--border)] rounded-md bg-[var(--card)]">
        <Calendar className="h-4 w-4 text-[var(--muted-foreground)]" />
        <input
          type="date"
          value={date}
          onChange={(e) => onDateChange(e.target.value)}
          className="bg-transparent focus:outline-none"
        />
      </div>
      <button
        type="button"
        onClick={goToNextDay}
        className="p-2 border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={goToToday}
        className="px-3 py-2 text-sm border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
      >
        Heute
      </button>
    </div>
  );
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function TeamsDailyPage() {
  const { currentSite } = useTenant();
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [assignments, setAssignments] = useState<TeamDailyAssignment[]>([]);
  const [summary, setSummary] = useState<ComplianceSummary>({
    total_teams: 0,
    matched: 0,
    mismatch_under: 0,
    mismatch_over: 0,
    can_publish: true,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isCheckingCompliance, setIsCheckingCompliance] = useState(false);

  // Fetch assignments
  const fetchAssignments = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`/api/tenant/teams/daily?date=${date}`);
      if (res.ok) {
        const data = await res.json();
        setAssignments(data.assignments || []);
        setSummary(data.summary || {
          total_teams: 0,
          matched: 0,
          mismatch_under: 0,
          mismatch_over: 0,
          can_publish: true,
        });
      }
    } catch (err) {
      console.error('Failed to fetch assignments:', err);
    } finally {
      setIsLoading(false);
    }
  }, [date]);

  useEffect(() => {
    fetchAssignments();
  }, [fetchAssignments]);

  // Check compliance
  const handleCheckCompliance = async () => {
    setIsCheckingCompliance(true);
    try {
      const res = await fetch(`/api/tenant/teams/daily/check-compliance?date=${date}`);
      if (res.ok) {
        const data = await res.json();
        // Refresh assignments to get updated demand_status
        fetchAssignments();
      }
    } catch (err) {
      console.error('Compliance check failed:', err);
    } finally {
      setIsCheckingCompliance(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Teams Daily</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Tagesplanung mit 2-Person Enforcement - {currentSite?.name}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <DateSelector date={date} onDateChange={setDate} />
          <button
            type="button"
            onClick={fetchAssignments}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
          >
            <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* Compliance Summary */}
      <ComplianceSummaryCard
        summary={summary}
        onCheckCompliance={handleCheckCompliance}
        isLoading={isCheckingCompliance}
      />

      {/* Team Cards */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-[var(--sv-primary)]" />
        </div>
      ) : assignments.length === 0 ? (
        <div className="text-center py-12 text-[var(--muted-foreground)]">
          <Users className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>Keine Teams fuer diesen Tag</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {assignments.map((assignment) => (
            <TeamCard key={assignment.id} assignment={assignment} />
          ))}
        </div>
      )}
    </div>
  );
}
