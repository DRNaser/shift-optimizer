// =============================================================================
// SOLVEREIGN Tenant - Scenario Detail Page
// =============================================================================
// /tenant/scenarios/[id]
//
// Scenario workflow:
//   CREATED => Solve => SOLVING => SOLVED => Audit => AUDITED => Lock => LOCKED
//
// Includes tabs for: Overview, Audit, Evidence, Repair
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Play,
  Shield,
  Lock,
  Download,
  Wrench,
  Loader2,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  MapPin,
  Truck,
  Package,
  Calendar,
  FileText,
  ExternalLink,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTenant } from '@/lib/hooks/use-tenant';
import { BlockedButton, useTenantStatus } from '@/components/tenant';
import type { RoutingScenario, RoutingPlan, AuditResult, EvidencePack, RepairEvent } from '@/lib/tenant-api';

// =============================================================================
// TABS
// =============================================================================

type TabId = 'overview' | 'audit' | 'evidence' | 'repair';

function Tabs({
  activeTab,
  onTabChange,
  hasAudit,
  hasEvidence,
  repairCount,
}: {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  hasAudit: boolean;
  hasEvidence: boolean;
  repairCount: number;
}) {
  const tabs: { id: TabId; label: string; icon: typeof Shield }[] = [
    { id: 'overview', label: 'Uebersicht', icon: MapPin },
    { id: 'audit', label: 'Audit', icon: Shield },
    { id: 'evidence', label: 'Evidence', icon: FileText },
    { id: 'repair', label: 'Repair', icon: Wrench },
  ];

  return (
    <div className="border-b border-[var(--border)]">
      <div className="flex gap-1">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => onTabChange(id)}
            className={cn(
              'flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors',
              activeTab === id
                ? 'border-[var(--sv-primary)] text-[var(--sv-primary)]'
                : 'border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
            {id === 'repair' && repairCount > 0 && (
              <span className="px-1.5 py-0.5 text-xs bg-[var(--sv-warning)] text-white rounded-full">
                {repairCount}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// OVERVIEW TAB
// =============================================================================

function OverviewTab({
  scenario,
  plan,
  onSolve,
  onLock,
  isLoading,
}: {
  scenario: RoutingScenario;
  plan: RoutingPlan | null;
  onSolve: () => void;
  onLock: () => void;
  isLoading: boolean;
}) {
  const canSolve = scenario.status === 'CREATED' || scenario.status === 'FAILED';
  const canLock = plan?.status === 'AUDITED';
  const isLocked = plan?.status === 'LOCKED';

  return (
    <div className="space-y-6">
      {/* Scenario Info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 border border-[var(--border)] rounded-lg">
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Calendar className="h-4 w-4" />
            Planungsdatum
          </div>
          <div className="mt-1 font-semibold">{scenario.plan_date}</div>
        </div>
        <div className="p-4 border border-[var(--border)] rounded-lg">
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Package className="h-4 w-4" />
            Stops
          </div>
          <div className="mt-1 font-semibold">{scenario.stops_count}</div>
        </div>
        <div className="p-4 border border-[var(--border)] rounded-lg">
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Truck className="h-4 w-4" />
            Fahrzeuge
          </div>
          <div className="mt-1 font-semibold">{scenario.vehicles_count}</div>
        </div>
        <div className="p-4 border border-[var(--border)] rounded-lg">
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <MapPin className="h-4 w-4" />
            Vertical
          </div>
          <div className="mt-1 font-semibold">{scenario.vertical}</div>
        </div>
      </div>

      {/* Plan Info (if exists) */}
      {plan && (
        <div className="border border-[var(--border)] rounded-lg p-6">
          <h3 className="font-semibold mb-4">Plan Ergebnisse</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <div className="text-sm text-[var(--muted-foreground)]">Status</div>
              <div className={cn(
                'mt-1 font-semibold',
                plan.status === 'LOCKED' ? 'text-[var(--sv-success)]' : ''
              )}>
                {plan.status}
              </div>
            </div>
            <div>
              <div className="text-sm text-[var(--muted-foreground)]">Genutzte Fahrzeuge</div>
              <div className="mt-1 font-semibold">{plan.total_vehicles || '-'}</div>
            </div>
            <div>
              <div className="text-sm text-[var(--muted-foreground)]">Distanz</div>
              <div className="mt-1 font-semibold">{plan.total_distance_km?.toFixed(1) || '-'} km</div>
            </div>
            <div>
              <div className="text-sm text-[var(--muted-foreground)]">Unassigned</div>
              <div className={cn(
                'mt-1 font-semibold',
                (plan.unassigned_count || 0) > 0 ? 'text-[var(--sv-warning)]' : ''
              )}>
                {plan.unassigned_count || 0}
              </div>
            </div>
            <div>
              <div className="text-sm text-[var(--muted-foreground)]">On-Time</div>
              <div className="mt-1 font-semibold">{plan.on_time_percentage?.toFixed(1) || '-'}%</div>
            </div>
          </div>

          {plan.locked_at && (
            <div className="mt-4 text-sm text-[var(--muted-foreground)]">
              Gesperrt am {new Date(plan.locked_at).toLocaleString('de-DE')} von {plan.locked_by}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        {canSolve && (
          <BlockedButton
            onClick={onSolve}
            disabled={isLoading}
            className="flex items-center gap-2 px-6 py-3 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)] disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Solver starten
          </BlockedButton>
        )}
        {canLock && (
          <BlockedButton
            onClick={onLock}
            disabled={isLoading}
            className="flex items-center gap-2 px-6 py-3 bg-[var(--sv-success)] text-white rounded-md hover:bg-green-700 disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
            Plan freigeben
          </BlockedButton>
        )}
        {isLocked && (
          <div className="flex items-center gap-2 px-6 py-3 bg-[var(--sv-success-light)] text-[var(--sv-success)] rounded-md">
            <Lock className="h-4 w-4" />
            Plan freigegeben
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// AUDIT TAB
// =============================================================================

function AuditTab({
  planId,
  audits,
  onRunAudit,
  isLoading,
}: {
  planId: string | null;
  audits: AuditResult[];
  onRunAudit: () => void;
  isLoading: boolean;
}) {
  if (!planId) {
    return (
      <div className="text-center py-12 text-[var(--muted-foreground)]">
        <Shield className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>Kein Plan vorhanden. Bitte zuerst Solver starten.</p>
      </div>
    );
  }

  const allPassed = audits.every(a => a.status === 'PASS' || a.status === 'WARN');
  const failCount = audits.filter(a => a.status === 'FAIL').length;

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className={cn(
        'border rounded-lg p-6',
        failCount > 0 ? 'border-[var(--sv-error)] bg-[var(--sv-error-light)]' : 'border-[var(--border)]'
      )}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {allPassed ? (
              <CheckCircle className="h-6 w-6 text-[var(--sv-success)]" />
            ) : (
              <XCircle className="h-6 w-6 text-[var(--sv-error)]" />
            )}
            <div>
              <h3 className="font-semibold">
                {allPassed ? 'Alle Audits bestanden' : `${failCount} Audit(s) fehlgeschlagen`}
              </h3>
              <p className="text-sm text-[var(--muted-foreground)]">
                {audits.length} Checks ausgefuehrt
              </p>
            </div>
          </div>
          <BlockedButton
            onClick={onRunAudit}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)] disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Audit erneut ausfuehren
          </BlockedButton>
        </div>
      </div>

      {/* Audit Results */}
      <div className="space-y-3">
        {audits.map((audit, idx) => (
          <div
            key={idx}
            className={cn(
              'border rounded-lg p-4 flex items-center justify-between',
              audit.status === 'PASS' && 'border-[var(--sv-success-light)]',
              audit.status === 'WARN' && 'border-[var(--sv-warning-light)]',
              audit.status === 'FAIL' && 'border-[var(--sv-error)]'
            )}
          >
            <div className="flex items-center gap-3">
              {audit.status === 'PASS' && <CheckCircle className="h-5 w-5 text-[var(--sv-success)]" />}
              {audit.status === 'WARN' && <AlertTriangle className="h-5 w-5 text-[var(--sv-warning)]" />}
              {audit.status === 'FAIL' && <XCircle className="h-5 w-5 text-[var(--sv-error)]" />}
              <div>
                <div className="font-medium">{audit.check_name}</div>
                {audit.violation_count > 0 && (
                  <div className="text-sm text-[var(--muted-foreground)]">
                    {audit.violation_count} Verstoesse
                  </div>
                )}
              </div>
            </div>
            <span className={cn(
              'px-2.5 py-1 rounded-full text-xs font-medium',
              audit.status === 'PASS' && 'bg-[var(--sv-success-light)] text-[var(--sv-success)]',
              audit.status === 'WARN' && 'bg-[var(--sv-warning-light)] text-[var(--sv-warning)]',
              audit.status === 'FAIL' && 'bg-[var(--sv-error-light)] text-[var(--sv-error)]'
            )}>
              {audit.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// EVIDENCE TAB
// =============================================================================

function EvidenceTab({
  planId,
  evidence,
  onGenerate,
  isLoading,
}: {
  planId: string | null;
  evidence: EvidencePack | null;
  onGenerate: () => void;
  isLoading: boolean;
}) {
  if (!planId) {
    return (
      <div className="text-center py-12 text-[var(--muted-foreground)]">
        <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>Kein Plan vorhanden.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {evidence ? (
        <div className="border border-[var(--border)] rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <FileText className="h-6 w-6 text-[var(--sv-primary)]" />
              <div>
                <h3 className="font-semibold">Evidence Pack</h3>
                <p className="text-sm text-[var(--muted-foreground)]">
                  Erstellt: {new Date(evidence.created_at).toLocaleString('de-DE')}
                </p>
              </div>
            </div>
            <a
              href={evidence.artifact_url}
              download
              className="flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)]"
            >
              <Download className="h-4 w-4" />
              Download
            </a>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-[var(--muted-foreground)]">SHA256:</span>
              <code className="ml-2 px-2 py-0.5 bg-[var(--muted)] rounded text-xs">
                {evidence.sha256_hash.substring(0, 16)}...
              </code>
            </div>
            <div>
              <span className="text-[var(--muted-foreground)]">Groesse:</span>
              <span className="ml-2">{(evidence.size_bytes / 1024).toFixed(1)} KB</span>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center py-12">
          <FileText className="h-12 w-12 mx-auto mb-4 text-[var(--muted-foreground)] opacity-50" />
          <p className="text-[var(--muted-foreground)] mb-4">Kein Evidence Pack vorhanden</p>
          <BlockedButton
            onClick={onGenerate}
            disabled={isLoading}
            className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)] disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
            Evidence Pack generieren
          </BlockedButton>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// REPAIR TAB
// =============================================================================

function RepairTab({
  planId,
  repairs,
  onCreateRepair,
  isLoading,
}: {
  planId: string | null;
  repairs: RepairEvent[];
  onCreateRepair: (type: RepairEvent['event_type']) => void;
  isLoading: boolean;
}) {
  if (!planId) {
    return (
      <div className="text-center py-12 text-[var(--muted-foreground)]">
        <Wrench className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>Kein Plan vorhanden.</p>
      </div>
    );
  }

  const eventTypes: { type: RepairEvent['event_type']; label: string; icon: typeof AlertTriangle }[] = [
    { type: 'NO_SHOW', label: 'No-Show', icon: XCircle },
    { type: 'DELAY', label: 'Verspaetung', icon: Clock },
    { type: 'VEHICLE_DOWN', label: 'Fahrzeugausfall', icon: Truck },
    { type: 'MANUAL', label: 'Manuell', icon: Wrench },
  ];

  return (
    <div className="space-y-6">
      {/* Create Repair */}
      <div className="border border-[var(--border)] rounded-lg p-6">
        <h3 className="font-semibold mb-4">Neuen Repair-Event erstellen</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {eventTypes.map(({ type, label, icon: Icon }) => (
            <BlockedButton
              key={type}
              onClick={() => onCreateRepair(type)}
              disabled={isLoading}
              className="flex flex-col items-center gap-2 p-4 border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] disabled:opacity-50"
            >
              <Icon className="h-5 w-5" />
              <span className="text-sm">{label}</span>
            </BlockedButton>
          ))}
        </div>
      </div>

      {/* Repair History */}
      <div>
        <h3 className="font-semibold mb-4">Repair Historie</h3>
        {repairs.length === 0 ? (
          <div className="text-center py-8 text-[var(--muted-foreground)]">
            Keine Repair-Events vorhanden
          </div>
        ) : (
          <div className="space-y-3">
            {repairs.map((repair) => (
              <div key={repair.id} className="border border-[var(--border)] rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={cn(
                      'px-2.5 py-1 rounded-full text-xs font-medium',
                      repair.status === 'COMPLETED' && 'bg-[var(--sv-success-light)] text-[var(--sv-success)]',
                      repair.status === 'PENDING' && 'bg-[var(--sv-warning-light)] text-[var(--sv-warning)]',
                      repair.status === 'PROCESSING' && 'bg-[var(--sv-info-light)] text-[var(--sv-info)]',
                      repair.status === 'FAILED' && 'bg-[var(--sv-error-light)] text-[var(--sv-error)]'
                    )}>
                      {repair.event_type}
                    </span>
                    <span className="text-sm text-[var(--muted-foreground)]">
                      {new Date(repair.initiated_at).toLocaleString('de-DE')}
                    </span>
                  </div>
                  <span className="text-sm">{repair.status}</span>
                </div>
                <div className="mt-2 text-sm text-[var(--muted-foreground)]">
                  {repair.affected_stop_ids.length} Stop(s) betroffen
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function ScenarioDetailPage() {
  const params = useParams();
  const router = useRouter();
  const scenarioId = params.id as string;

  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [scenario, setScenario] = useState<RoutingScenario | null>(null);
  const [plan, setPlan] = useState<RoutingPlan | null>(null);
  const [audits, setAudits] = useState<AuditResult[]>([]);
  const [evidence, setEvidence] = useState<EvidencePack | null>(null);
  const [repairs, setRepairs] = useState<RepairEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Fetch scenario
  const fetchScenario = useCallback(async () => {
    try {
      const res = await fetch(`/api/tenant/scenarios/${scenarioId}`);
      if (res.ok) {
        setScenario(await res.json());
      }
    } catch (err) {
      console.error('Failed to fetch scenario:', err);
    }
  }, [scenarioId]);

  // Fetch plan using scenario.latest_plan_id (Blueprint v6: no hardcoded IDs)
  const fetchPlan = useCallback(async () => {
    if (!scenario?.latest_plan_id) {
      setPlan(null);  // Not solved yet
      return;
    }
    try {
      const res = await fetch(`/api/tenant/plans/${scenario.latest_plan_id}`);
      if (res.ok) {
        setPlan(await res.json());
      }
    } catch (err) {
      // No plan yet
    }
  }, [scenario?.latest_plan_id]);

  // Fetch audits
  const fetchAudits = useCallback(async () => {
    if (!plan?.id) return;
    try {
      const res = await fetch(`/api/tenant/plans/${plan.id}/audit`);
      if (res.ok) {
        const data = await res.json();
        setAudits(data.results || []);
      }
    } catch (err) {
      console.error('Failed to fetch audits:', err);
    }
  }, [plan?.id]);

  // Fetch evidence
  const fetchEvidence = useCallback(async () => {
    if (!plan?.id) return;
    try {
      const res = await fetch(`/api/tenant/plans/${plan.id}/evidence`);
      if (res.ok) {
        setEvidence(await res.json());
      }
    } catch (err) {
      // No evidence yet
    }
  }, [plan?.id]);

  // Fetch repairs
  const fetchRepairs = useCallback(async () => {
    if (!plan?.id) return;
    try {
      const res = await fetch(`/api/tenant/plans/${plan.id}/repair`);
      if (res.ok) {
        setRepairs(await res.json());
      }
    } catch (err) {
      console.error('Failed to fetch repairs:', err);
    }
  }, [plan?.id]);

  useEffect(() => {
    fetchScenario();
    fetchPlan();
  }, [fetchScenario, fetchPlan]);

  useEffect(() => {
    if (plan?.id) {
      fetchAudits();
      fetchEvidence();
      fetchRepairs();
    }
  }, [plan?.id, fetchAudits, fetchEvidence, fetchRepairs]);

  // Actions
  const handleSolve = async () => {
    setIsLoading(true);
    try {
      await fetch(`/api/tenant/scenarios/${scenarioId}/solve`, { method: 'POST' });
      fetchScenario();
      fetchPlan();
    } finally {
      setIsLoading(false);
    }
  };

  const handleLock = async () => {
    if (!plan?.id) return;
    setIsLoading(true);
    try {
      await fetch(`/api/tenant/plans/${plan.id}/lock`, { method: 'POST' });
      fetchPlan();
    } finally {
      setIsLoading(false);
    }
  };

  const handleRunAudit = async () => {
    if (!plan?.id) return;
    setIsLoading(true);
    try {
      await fetch(`/api/tenant/plans/${plan.id}/audit`, { method: 'POST' });
      fetchAudits();
    } finally {
      setIsLoading(false);
    }
  };

  const handleGenerateEvidence = async () => {
    if (!plan?.id) return;
    setIsLoading(true);
    try {
      await fetch(`/api/tenant/plans/${plan.id}/evidence`, { method: 'POST' });
      fetchEvidence();
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateRepair = async (type: RepairEvent['event_type']) => {
    if (!plan?.id) return;
    setIsLoading(true);
    try {
      await fetch(`/api/tenant/plans/${plan.id}/repair`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type: type, affected_stop_ids: ['stop-001'] }),
      });
      fetchRepairs();
    } finally {
      setIsLoading(false);
    }
  };

  if (!scenario) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--sv-primary)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          href="/scenarios"
          className="p-2 hover:bg-[var(--muted)] rounded-md"
        >
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-semibold">
            {scenario.vertical} - {scenario.plan_date}
          </h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Szenario {scenario.id}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        activeTab={activeTab}
        onTabChange={setActiveTab}
        hasAudit={audits.length > 0}
        hasEvidence={evidence !== null}
        repairCount={repairs.length}
      />

      {/* Tab Content */}
      <div className="py-4">
        {activeTab === 'overview' && (
          <OverviewTab
            scenario={scenario}
            plan={plan}
            onSolve={handleSolve}
            onLock={handleLock}
            isLoading={isLoading}
          />
        )}
        {activeTab === 'audit' && (
          <AuditTab
            planId={plan?.id || null}
            audits={audits}
            onRunAudit={handleRunAudit}
            isLoading={isLoading}
          />
        )}
        {activeTab === 'evidence' && (
          <EvidenceTab
            planId={plan?.id || null}
            evidence={evidence}
            onGenerate={handleGenerateEvidence}
            isLoading={isLoading}
          />
        )}
        {activeTab === 'repair' && (
          <RepairTab
            planId={plan?.id || null}
            repairs={repairs}
            onCreateRepair={handleCreateRepair}
            isLoading={isLoading}
          />
        )}
      </div>
    </div>
  );
}
