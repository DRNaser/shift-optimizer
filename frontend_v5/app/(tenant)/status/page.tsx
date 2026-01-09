// =============================================================================
// SOLVEREIGN Tenant - Status Page
// =============================================================================
// /tenant/status
//
// Shows:
// - Current operational status (healthy/degraded/blocked)
// - Active escalations with severity (S0-S3)
// - Status history timeline
// - Degraded service details
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  RefreshCw,
  Shield,
  AlertOctagon,
  Bell,
  History,
  Server,
  Loader2,
  ChevronRight,
  ExternalLink,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTenant } from '@/lib/hooks/use-tenant';

// =============================================================================
// TYPES
// =============================================================================

type OperationalStatus = 'healthy' | 'degraded' | 'blocked';
type EscalationSeverity = 'S0' | 'S1' | 'S2' | 'S3';
type EscalationStatus = 'OPEN' | 'ACKNOWLEDGED' | 'IN_PROGRESS' | 'RESOLVED';

interface Escalation {
  id: string;
  tenant_id: string;
  site_id: string | null;
  severity: EscalationSeverity;
  category: string;
  title: string;
  description: string;
  status: EscalationStatus;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
}

interface StatusHistoryEntry {
  id: string;
  timestamp: string;
  old_status: OperationalStatus;
  new_status: OperationalStatus;
  reason: string;
  changed_by: string | null;
}

interface DegradedService {
  service: string;
  status: 'degraded' | 'unavailable';
  message: string;
  estimated_recovery: string | null;
}

interface StatusDetails {
  tenant_code: string;
  site_code: string;
  current_status: OperationalStatus;
  is_write_blocked: boolean;
  blocked_reason: string | null;
  degraded_services: DegradedService[];
  active_escalations: Escalation[];
  status_history: StatusHistoryEntry[];
  last_health_check: string;
}

// =============================================================================
// STATUS INDICATOR
// =============================================================================

function StatusIndicator({ status }: { status: OperationalStatus }) {
  const config: Record<OperationalStatus, { color: string; bgColor: string; icon: typeof CheckCircle; label: string }> = {
    healthy: {
      color: 'text-[var(--sv-success)]',
      bgColor: 'bg-[var(--sv-success)]',
      icon: CheckCircle,
      label: 'Betriebsbereit',
    },
    degraded: {
      color: 'text-[var(--sv-warning)]',
      bgColor: 'bg-[var(--sv-warning)]',
      icon: AlertTriangle,
      label: 'Eingeschraenkt',
    },
    blocked: {
      color: 'text-[var(--sv-error)]',
      bgColor: 'bg-[var(--sv-error)]',
      icon: XCircle,
      label: 'Blockiert',
    },
  };

  const { color, bgColor, icon: Icon, label } = config[status];

  return (
    <div className="flex items-center gap-4">
      <div className={cn('relative h-16 w-16 rounded-full flex items-center justify-center', color)}>
        <div className={cn('absolute inset-0 rounded-full opacity-20', bgColor)} />
        <Icon className="h-8 w-8" />
        {status === 'healthy' && (
          <span className={cn('absolute -top-1 -right-1 h-4 w-4 rounded-full animate-pulse', bgColor)} />
        )}
      </div>
      <div>
        <div className={cn('text-2xl font-bold', color)}>{label}</div>
        <div className="text-sm text-[var(--muted-foreground)]">Aktueller Status</div>
      </div>
    </div>
  );
}

// =============================================================================
// SEVERITY BADGE
// =============================================================================

function SeverityBadge({ severity }: { severity: EscalationSeverity }) {
  const config: Record<EscalationSeverity, { color: string; label: string; description: string }> = {
    S0: { color: 'bg-[var(--sv-error)] text-white', label: 'S0', description: 'Kritisch' },
    S1: { color: 'bg-orange-500 text-white', label: 'S1', description: 'Hoch' },
    S2: { color: 'bg-[var(--sv-warning)] text-black', label: 'S2', description: 'Mittel' },
    S3: { color: 'bg-[var(--sv-info)] text-white', label: 'S3', description: 'Niedrig' },
  };

  const { color, label, description } = config[severity];

  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold', color)}>
      {label}
      <span className="font-normal opacity-80">({description})</span>
    </span>
  );
}

// =============================================================================
// ESCALATION STATUS BADGE
// =============================================================================

function EscalationStatusBadge({ status }: { status: EscalationStatus }) {
  const config: Record<EscalationStatus, { color: string; label: string }> = {
    OPEN: { color: 'text-[var(--sv-error)] bg-[var(--sv-error-light)]', label: 'Offen' },
    ACKNOWLEDGED: { color: 'text-[var(--sv-warning)] bg-[var(--sv-warning-light)]', label: 'Bestaetigt' },
    IN_PROGRESS: { color: 'text-[var(--sv-info)] bg-[var(--sv-info-light)]', label: 'In Bearbeitung' },
    RESOLVED: { color: 'text-[var(--sv-success)] bg-[var(--sv-success-light)]', label: 'Geloest' },
  };

  const { color, label } = config[status];

  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 rounded text-xs font-medium', color)}>
      {label}
    </span>
  );
}

// =============================================================================
// ESCALATION CARD
// =============================================================================

function EscalationCard({ escalation }: { escalation: Escalation }) {
  const formatDate = (date: string) => new Date(date).toLocaleString('de-DE');

  return (
    <div className="border border-[var(--border)] rounded-lg p-4 bg-[var(--card)]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <SeverityBadge severity={escalation.severity} />
            <EscalationStatusBadge status={escalation.status} />
            <span className="text-xs text-[var(--muted-foreground)] px-2 py-0.5 bg-[var(--muted)] rounded">
              {escalation.category}
            </span>
          </div>
          <h3 className="font-medium mb-1">{escalation.title}</h3>
          <p className="text-sm text-[var(--muted-foreground)]">{escalation.description}</p>
        </div>
        <AlertOctagon className={cn(
          'h-5 w-5 flex-shrink-0',
          escalation.severity === 'S0' ? 'text-[var(--sv-error)]' :
          escalation.severity === 'S1' ? 'text-orange-500' :
          escalation.severity === 'S2' ? 'text-[var(--sv-warning)]' :
          'text-[var(--sv-info)]'
        )} />
      </div>

      <div className="mt-4 flex items-center gap-4 text-xs text-[var(--muted-foreground)]">
        <div className="flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          Erstellt: {formatDate(escalation.created_at)}
        </div>
        {escalation.acknowledged_at && (
          <div className="flex items-center gap-1">
            <CheckCircle className="h-3.5 w-3.5" />
            Bestaetigt: {formatDate(escalation.acknowledged_at)}
          </div>
        )}
      </div>

      {escalation.resolution_note && (
        <div className="mt-3 p-2 bg-[var(--sv-success-light)] rounded text-sm">
          <span className="font-medium text-[var(--sv-success)]">Loesung:</span>{' '}
          {escalation.resolution_note}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// DEGRADED SERVICE CARD
// =============================================================================

function DegradedServiceCard({ service }: { service: DegradedService }) {
  const isUnavailable = service.status === 'unavailable';

  return (
    <div className={cn(
      'border rounded-lg p-4',
      isUnavailable ? 'border-[var(--sv-error)] bg-[var(--sv-error-light)]' : 'border-[var(--sv-warning)] bg-[var(--sv-warning-light)]'
    )}>
      <div className="flex items-center gap-3">
        <Server className={cn('h-5 w-5', isUnavailable ? 'text-[var(--sv-error)]' : 'text-[var(--sv-warning)]')} />
        <div className="flex-1">
          <div className="font-medium">{service.service}</div>
          <div className="text-sm text-[var(--muted-foreground)]">{service.message}</div>
        </div>
        <span className={cn(
          'px-2 py-0.5 rounded text-xs font-medium',
          isUnavailable ? 'bg-[var(--sv-error)] text-white' : 'bg-[var(--sv-warning)] text-black'
        )}>
          {isUnavailable ? 'Nicht verfuegbar' : 'Eingeschraenkt'}
        </span>
      </div>
      {service.estimated_recovery && (
        <div className="mt-2 text-xs text-[var(--muted-foreground)]">
          Erwartete Wiederherstellung: {new Date(service.estimated_recovery).toLocaleString('de-DE')}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// STATUS HISTORY TIMELINE
// =============================================================================

function StatusHistoryTimeline({ history }: { history: StatusHistoryEntry[] }) {
  const getStatusColor = (status: OperationalStatus) => {
    switch (status) {
      case 'healthy': return 'bg-[var(--sv-success)]';
      case 'degraded': return 'bg-[var(--sv-warning)]';
      case 'blocked': return 'bg-[var(--sv-error)]';
    }
  };

  const getStatusLabel = (status: OperationalStatus) => {
    switch (status) {
      case 'healthy': return 'Betriebsbereit';
      case 'degraded': return 'Eingeschraenkt';
      case 'blocked': return 'Blockiert';
    }
  };

  return (
    <div className="space-y-4">
      {history.map((entry, idx) => (
        <div key={entry.id} className="flex gap-4">
          <div className="flex flex-col items-center">
            <div className={cn('h-3 w-3 rounded-full', getStatusColor(entry.new_status))} />
            {idx < history.length - 1 && (
              <div className="w-0.5 h-full bg-[var(--border)] mt-1" />
            )}
          </div>
          <div className="flex-1 pb-4">
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium">{getStatusLabel(entry.old_status)}</span>
              <ChevronRight className="h-3 w-3 text-[var(--muted-foreground)]" />
              <span className="font-medium">{getStatusLabel(entry.new_status)}</span>
            </div>
            <div className="text-sm text-[var(--muted-foreground)] mt-1">{entry.reason}</div>
            <div className="text-xs text-[var(--muted-foreground)] mt-1">
              {new Date(entry.timestamp).toLocaleString('de-DE')}
              {entry.changed_by && ` - ${entry.changed_by}`}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function StatusPage() {
  const { currentSite } = useTenant();
  const [statusDetails, setStatusDetails] = useState<StatusDetails | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchStatusDetails = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/tenant/status/details');
      if (res.ok) {
        const data = await res.json();
        setStatusDetails(data);
      }
    } catch (err) {
      console.error('Failed to fetch status details:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatusDetails();
    // Auto-refresh every 60 seconds
    const interval = setInterval(fetchStatusDetails, 60000);
    return () => clearInterval(interval);
  }, [fetchStatusDetails]);

  if (isLoading && !statusDetails) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--sv-primary)]" />
      </div>
    );
  }

  if (!statusDetails) {
    return (
      <div className="text-center py-24 text-[var(--muted-foreground)]">
        <AlertTriangle className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>Status konnte nicht geladen werden</p>
      </div>
    );
  }

  const activeEscalations = statusDetails.active_escalations.filter(e => e.status !== 'RESOLVED');
  const resolvedEscalations = statusDetails.active_escalations.filter(e => e.status === 'RESOLVED');

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">System Status</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Betriebsstatus und Eskalationen - {currentSite?.name}
          </p>
        </div>
        <button
          type="button"
          onClick={fetchStatusDetails}
          disabled={isLoading}
          className="flex items-center gap-2 px-3 py-2 text-sm border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
        >
          <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          Aktualisieren
        </button>
      </div>

      {/* Status Overview */}
      <div className="border border-[var(--border)] rounded-lg p-6 bg-[var(--card)]">
        <div className="flex items-center justify-between">
          <StatusIndicator status={statusDetails.current_status} />
          <div className="text-right text-sm text-[var(--muted-foreground)]">
            <div>Letzte Pruefung</div>
            <div className="font-medium">
              {new Date(statusDetails.last_health_check).toLocaleString('de-DE')}
            </div>
          </div>
        </div>

        {statusDetails.blocked_reason && (
          <div className="mt-4 p-3 bg-[var(--sv-error-light)] border border-[var(--sv-error)] rounded-md">
            <div className="flex items-center gap-2 text-[var(--sv-error)]">
              <Shield className="h-5 w-5" />
              <span className="font-medium">Blockierungsgrund:</span>
            </div>
            <p className="mt-1 text-sm">{statusDetails.blocked_reason}</p>
          </div>
        )}

        {/* Quick Stats */}
        <div className="mt-6 grid grid-cols-3 gap-4">
          <div className="text-center p-4 bg-[var(--muted)] rounded-lg">
            <div className="text-3xl font-bold text-[var(--sv-primary)]">
              {activeEscalations.length}
            </div>
            <div className="text-sm text-[var(--muted-foreground)]">Aktive Eskalationen</div>
          </div>
          <div className="text-center p-4 bg-[var(--muted)] rounded-lg">
            <div className="text-3xl font-bold">
              {statusDetails.degraded_services.length}
            </div>
            <div className="text-sm text-[var(--muted-foreground)]">Eingeschraenkte Dienste</div>
          </div>
          <div className="text-center p-4 bg-[var(--muted)] rounded-lg">
            <div className="text-3xl font-bold">
              {statusDetails.status_history.length}
            </div>
            <div className="text-sm text-[var(--muted-foreground)]">Aenderungen (30 Tage)</div>
          </div>
        </div>
      </div>

      {/* Degraded Services */}
      {statusDetails.degraded_services.length > 0 && (
        <div>
          <h2 className="text-lg font-medium mb-4 flex items-center gap-2">
            <Server className="h-5 w-5 text-[var(--sv-warning)]" />
            Eingeschraenkte Dienste
          </h2>
          <div className="space-y-3">
            {statusDetails.degraded_services.map((service, idx) => (
              <DegradedServiceCard key={idx} service={service} />
            ))}
          </div>
        </div>
      )}

      {/* Active Escalations */}
      <div>
        <h2 className="text-lg font-medium mb-4 flex items-center gap-2">
          <Bell className="h-5 w-5 text-[var(--sv-primary)]" />
          Aktive Eskalationen
          {activeEscalations.length > 0 && (
            <span className="px-2 py-0.5 bg-[var(--sv-primary)] text-white text-xs rounded-full">
              {activeEscalations.length}
            </span>
          )}
        </h2>
        {activeEscalations.length === 0 ? (
          <div className="text-center py-8 border border-[var(--border)] rounded-lg bg-[var(--card)]">
            <CheckCircle className="h-12 w-12 mx-auto mb-4 text-[var(--sv-success)] opacity-50" />
            <p className="text-[var(--muted-foreground)]">Keine aktiven Eskalationen</p>
          </div>
        ) : (
          <div className="space-y-3">
            {activeEscalations.map((escalation) => (
              <EscalationCard key={escalation.id} escalation={escalation} />
            ))}
          </div>
        )}
      </div>

      {/* Recently Resolved */}
      {resolvedEscalations.length > 0 && (
        <div>
          <h2 className="text-lg font-medium mb-4 flex items-center gap-2">
            <CheckCircle className="h-5 w-5 text-[var(--sv-success)]" />
            Kuerzlich geloest
          </h2>
          <div className="space-y-3 opacity-75">
            {resolvedEscalations.slice(0, 3).map((escalation) => (
              <EscalationCard key={escalation.id} escalation={escalation} />
            ))}
          </div>
        </div>
      )}

      {/* Status History */}
      <div>
        <h2 className="text-lg font-medium mb-4 flex items-center gap-2">
          <History className="h-5 w-5" />
          Statusverlauf
        </h2>
        <div className="border border-[var(--border)] rounded-lg p-4 bg-[var(--card)]">
          {statusDetails.status_history.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              <Activity className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>Keine Statusaenderungen in den letzten 30 Tagen</p>
            </div>
          ) : (
            <StatusHistoryTimeline history={statusDetails.status_history} />
          )}
        </div>
      </div>

      {/* Support Link */}
      <div className="border border-[var(--border)] rounded-lg p-4 bg-[var(--muted)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Shield className="h-5 w-5 text-[var(--sv-primary)]" />
            <div>
              <div className="font-medium">Support kontaktieren</div>
              <div className="text-sm text-[var(--muted-foreground)]">
                Bei dringenden Problemen wenden Sie sich an das SOLVEREIGN Support Team
              </div>
            </div>
          </div>
          <a
            href="mailto:support@solvereign.com"
            className="flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)]"
          >
            <ExternalLink className="h-4 w-4" />
            Kontakt
          </a>
        </div>
      </div>
    </div>
  );
}
