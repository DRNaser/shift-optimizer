// =============================================================================
// SOLVEREIGN Tenant - Scenarios List Page
// =============================================================================
// /tenant/scenarios
//
// Lists all routing scenarios for the current site.
// Actions: Create new scenario, view details, solve.
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import {
  Plus,
  Calendar,
  MapPin,
  Truck,
  Package,
  Loader2,
  RefreshCw,
  ChevronRight,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTenant } from '@/lib/hooks/use-tenant';
import { BlockedButton } from '@/components/tenant';
import type { RoutingScenario } from '@/lib/tenant-api';

// =============================================================================
// STATUS BADGE
// =============================================================================

function ScenarioStatusBadge({ status }: { status: RoutingScenario['status'] }) {
  const configs: Record<RoutingScenario['status'], { icon: typeof Clock; color: string; label: string }> = {
    CREATED: { icon: Clock, color: 'text-[var(--sv-gray-500)] bg-[var(--sv-gray-100)]', label: 'Erstellt' },
    SOLVING: { icon: Loader2, color: 'text-[var(--sv-info)] bg-[var(--sv-info-light)]', label: 'Berechnung...' },
    SOLVED: { icon: CheckCircle, color: 'text-[var(--sv-success)] bg-[var(--sv-success-light)]', label: 'Geloest' },
    FAILED: { icon: XCircle, color: 'text-[var(--sv-error)] bg-[var(--sv-error-light)]', label: 'Fehler' },
  };

  const { icon: Icon, color, label } = configs[status];

  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium', color)}>
      <Icon className={cn('h-3.5 w-3.5', status === 'SOLVING' && 'animate-spin')} />
      {label}
    </span>
  );
}

// =============================================================================
// VERTICAL BADGE
// =============================================================================

function VerticalBadge({ vertical }: { vertical: 'MEDIAMARKT' | 'HDL_PLUS' }) {
  const configs: Record<string, { color: string; label: string }> = {
    MEDIAMARKT: { color: 'text-red-600 bg-red-100', label: 'MediaMarkt' },
    HDL_PLUS: { color: 'text-blue-600 bg-blue-100', label: 'HDL Plus' },
  };

  const { color, label } = configs[vertical];

  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 rounded text-xs font-medium', color)}>
      {label}
    </span>
  );
}

// =============================================================================
// SCENARIO CARD
// =============================================================================

function ScenarioCard({ scenario }: { scenario: RoutingScenario }) {
  return (
    <Link
      href={`/scenarios/${scenario.id}`}
      className="block border border-[var(--border)] rounded-lg p-4 bg-[var(--card)] hover:border-[var(--sv-primary)] transition-colors"
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[var(--muted)]">
            <MapPin className="h-5 w-5 text-[var(--sv-primary)]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-medium">
                {new Date(scenario.plan_date).toLocaleDateString('de-DE', {
                  weekday: 'short',
                  day: '2-digit',
                  month: '2-digit',
                  year: 'numeric',
                })}
              </h3>
              <VerticalBadge vertical={scenario.vertical} />
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              Erstellt: {new Date(scenario.created_at).toLocaleString('de-DE')}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ScenarioStatusBadge status={scenario.status} />
          <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
        </div>
      </div>

      {/* Stats */}
      <div className="mt-4 grid grid-cols-3 gap-4 text-center text-sm">
        <div className="flex items-center gap-2 justify-center">
          <Package className="h-4 w-4 text-[var(--muted-foreground)]" />
          <span>{scenario.stops_count} Stops</span>
        </div>
        <div className="flex items-center gap-2 justify-center">
          <Truck className="h-4 w-4 text-[var(--muted-foreground)]" />
          <span>{scenario.vehicles_count} Fahrzeuge</span>
        </div>
        <div className="flex items-center gap-2 justify-center">
          <Calendar className="h-4 w-4 text-[var(--muted-foreground)]" />
          <span>{scenario.plan_date}</span>
        </div>
      </div>

      {scenario.solved_at && (
        <div className="mt-3 text-xs text-[var(--muted-foreground)]">
          Geloest: {new Date(scenario.solved_at).toLocaleString('de-DE')}
        </div>
      )}
    </Link>
  );
}

// =============================================================================
// CREATE SCENARIO DIALOG
// =============================================================================

function CreateScenarioDialog({
  isOpen,
  onClose,
  onCreate,
  isLoading,
}: {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (data: { vertical: 'MEDIAMARKT' | 'HDL_PLUS'; plan_date: string }) => void;
  isLoading: boolean;
}) {
  const [vertical, setVertical] = useState<'MEDIAMARKT' | 'HDL_PLUS'>('MEDIAMARKT');
  const [planDate, setPlanDate] = useState(new Date().toISOString().split('T')[0]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-[var(--card)] rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
        <h2 className="text-lg font-semibold mb-4">Neues Szenario erstellen</h2>

        <div className="space-y-4">
          {/* Vertical Selection */}
          <div>
            <label className="block text-sm font-medium mb-2">Vertical</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setVertical('MEDIAMARKT')}
                className={cn(
                  'px-4 py-3 border rounded-lg text-sm font-medium transition-colors',
                  vertical === 'MEDIAMARKT'
                    ? 'border-red-500 bg-red-50 text-red-700'
                    : 'border-[var(--border)] hover:bg-[var(--muted)]'
                )}
              >
                MediaMarkt
              </button>
              <button
                type="button"
                onClick={() => setVertical('HDL_PLUS')}
                className={cn(
                  'px-4 py-3 border rounded-lg text-sm font-medium transition-colors',
                  vertical === 'HDL_PLUS'
                    ? 'border-blue-500 bg-blue-50 text-blue-700'
                    : 'border-[var(--border)] hover:bg-[var(--muted)]'
                )}
              >
                HDL Plus
              </button>
            </div>
          </div>

          {/* Date Selection */}
          <div>
            <label className="block text-sm font-medium mb-2">Planungsdatum</label>
            <input
              type="date"
              value={planDate}
              onChange={(e) => setPlanDate(e.target.value)}
              className="w-full px-3 py-2 border border-[var(--border)] rounded-md focus:outline-none focus:ring-2 focus:ring-[var(--sv-primary)]"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="mt-6 flex gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="flex-1 px-4 py-2 border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
          >
            Abbrechen
          </button>
          <button
            type="button"
            onClick={() => onCreate({ vertical, plan_date: planDate })}
            disabled={isLoading}
            className="flex-1 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)] disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : 'Erstellen'}
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function ScenariosPage() {
  const { currentSite } = useTenant();
  const [scenarios, setScenarios] = useState<RoutingScenario[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  // Fetch scenarios
  const fetchScenarios = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/tenant/scenarios');
      if (res.ok) {
        const data = await res.json();
        setScenarios(data);
      }
    } catch (err) {
      console.error('Failed to fetch scenarios:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchScenarios();
  }, [fetchScenarios]);

  // Create scenario
  const handleCreate = async (data: { vertical: 'MEDIAMARKT' | 'HDL_PLUS'; plan_date: string }) => {
    setIsCreating(true);
    try {
      const res = await fetch('/api/tenant/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (res.ok) {
        setShowCreateDialog(false);
        fetchScenarios();
      }
    } catch (err) {
      console.error('Create scenario failed:', err);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Szenarien</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Routing-Szenarien verwalten - {currentSite?.name}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchScenarios}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
          >
            <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          </button>
          <BlockedButton
            onClick={() => setShowCreateDialog(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)]"
          >
            <Plus className="h-4 w-4" />
            Neues Szenario
          </BlockedButton>
        </div>
      </div>

      {/* Scenarios List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-[var(--sv-primary)]" />
        </div>
      ) : scenarios.length === 0 ? (
        <div className="text-center py-12 text-[var(--muted-foreground)]">
          <MapPin className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>Keine Szenarien vorhanden</p>
          <BlockedButton
            onClick={() => setShowCreateDialog(true)}
            className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)]"
          >
            <Plus className="h-4 w-4" />
            Erstes Szenario erstellen
          </BlockedButton>
        </div>
      ) : (
        <div className="space-y-4">
          {scenarios.map((scenario) => (
            <ScenarioCard key={scenario.id} scenario={scenario} />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <CreateScenarioDialog
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onCreate={handleCreate}
        isLoading={isCreating}
      />
    </div>
  );
}
