// =============================================================================
// SOLVEREIGN Tenant Dashboard Page
// =============================================================================
// Main dashboard for tenant console showing KPIs, recent plans, and quick actions.
// =============================================================================

import { Metadata } from 'next';
import {
  Calendar,
  Users,
  CheckCircle2,
  AlertTriangle,
  TrendingUp,
  Clock,
  ArrowRight,
} from 'lucide-react';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Dashboard',
};

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--foreground)]">
            Dashboard
          </h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Übersicht Ihrer Schichtplanung
          </p>
        </div>
        <Link
          href="/scenarios/new"
          className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-hover)] transition-colors"
        >
          <Calendar className="h-4 w-4" />
          Neues Szenario
        </Link>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          title="Aktive Fahrer"
          value="145"
          change="+3"
          changeType="positive"
          icon={Users}
        />
        <KPICard
          title="Pläne diese Woche"
          value="12"
          change="+2"
          changeType="positive"
          icon={Calendar}
        />
        <KPICard
          title="Audit-Quote"
          value="98%"
          change="+2%"
          changeType="positive"
          icon={CheckCircle2}
        />
        <KPICard
          title="Offene Warnungen"
          value="3"
          change="-1"
          changeType="positive"
          icon={AlertTriangle}
        />
      </div>

      {/* Recent Plans & Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Plans */}
        <div className="lg:col-span-2 bg-[var(--card)] border border-[var(--border)] rounded-lg">
          <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
            <h2 className="font-medium text-[var(--foreground)]">
              Letzte Pläne
            </h2>
            <Link
              href="/plans"
              className="text-sm text-[var(--sv-primary)] hover:underline flex items-center gap-1"
            >
              Alle anzeigen <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="divide-y divide-[var(--border)]">
            <PlanRow
              name="KW02-2026"
              site="Hamburg Nord"
              status="LOCKED"
              drivers={145}
              coverage="100%"
              updatedAt="vor 2 Std"
            />
            <PlanRow
              name="KW03-2026"
              site="Hamburg Nord"
              status="AUDITED"
              drivers={142}
              coverage="100%"
              updatedAt="vor 5 Std"
            />
            <PlanRow
              name="KW02-2026"
              site="München West"
              status="SOLVING"
              drivers={null}
              coverage="--"
              updatedAt="gerade eben"
            />
            <PlanRow
              name="KW04-2026"
              site="Hamburg Nord"
              status="DRAFT"
              drivers={138}
              coverage="98%"
              updatedAt="vor 1 Tag"
            />
          </div>
        </div>

        {/* Quick Actions */}
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg">
          <div className="px-4 py-3 border-b border-[var(--border)]">
            <h2 className="font-medium text-[var(--foreground)]">
              Schnellaktionen
            </h2>
          </div>
          <div className="p-4 space-y-3">
            <QuickAction
              href="/scenarios/new"
              icon={Calendar}
              title="Forecast importieren"
              description="CSV oder manuell eingeben"
            />
            <QuickAction
              href="/plans"
              icon={TrendingUp}
              title="Plan optimieren"
              description="Neuen Solver-Lauf starten"
            />
            <QuickAction
              href="/audits"
              icon={CheckCircle2}
              title="Audits prüfen"
              description="Compliance-Checks ansehen"
            />
            <QuickAction
              href="/evidence"
              icon={Clock}
              title="Evidence exportieren"
              description="Nachweispakete herunterladen"
            />
          </div>
        </div>
      </div>

      {/* Activity Timeline */}
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg">
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <h2 className="font-medium text-[var(--foreground)]">
            Letzte Aktivitäten
          </h2>
        </div>
        <div className="p-4 space-y-4">
          <ActivityItem
            action="Plan freigegeben"
            details="KW02-2026 wurde von Max Müller freigegeben"
            time="vor 2 Std"
            type="success"
          />
          <ActivityItem
            action="Audit abgeschlossen"
            details="7/7 Checks bestanden für KW03-2026"
            time="vor 5 Std"
            type="success"
          />
          <ActivityItem
            action="Solver gestartet"
            details="Optimierung für KW02-2026 München West"
            time="gerade eben"
            type="info"
          />
          <ActivityItem
            action="Warnung"
            details="3er→3er Sequenz erkannt (Fahrer D-042)"
            time="vor 1 Tag"
            type="warning"
          />
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// SUB-COMPONENTS
// =============================================================================

interface KPICardProps {
  title: string;
  value: string;
  change: string;
  changeType: 'positive' | 'negative' | 'neutral';
  icon: React.ComponentType<{ className?: string }>;
}

function KPICard({ title, value, change, changeType, icon: Icon }: KPICardProps) {
  const changeColors = {
    positive: 'text-[var(--sv-success)]',
    negative: 'text-[var(--sv-error)]',
    neutral: 'text-[var(--muted-foreground)]',
  };

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-[var(--muted-foreground)]">{title}</span>
        <Icon className="h-4 w-4 text-[var(--muted-foreground)]" />
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-[var(--foreground)]">
          {value}
        </span>
        <span className={`text-sm ${changeColors[changeType]}`}>
          {change}
        </span>
      </div>
    </div>
  );
}

interface PlanRowProps {
  name: string;
  site: string;
  status: string;
  drivers: number | null;
  coverage: string;
  updatedAt: string;
}

function PlanRow({ name, site, status, drivers, coverage, updatedAt }: PlanRowProps) {
  const statusColors: Record<string, string> = {
    LOCKED: 'bg-[var(--sv-success)]/10 text-[var(--sv-success)]',
    AUDITED: 'bg-[var(--sv-success)]/10 text-[var(--sv-success)]',
    SOLVING: 'bg-[var(--sv-info)]/10 text-[var(--sv-info)]',
    DRAFT: 'bg-[var(--sv-warning)]/10 text-[var(--sv-warning)]',
    FAILED: 'bg-[var(--sv-error)]/10 text-[var(--sv-error)]',
  };

  return (
    <div className="px-4 py-3 flex items-center gap-4 hover:bg-[var(--muted)] transition-colors cursor-pointer">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--foreground)] truncate">
          {name}
        </p>
        <p className="text-xs text-[var(--muted-foreground)]">{site}</p>
      </div>
      <span className={`px-2 py-0.5 text-xs font-medium rounded ${statusColors[status] || statusColors.DRAFT}`}>
        {status}
      </span>
      <div className="hidden md:block text-right">
        <p className="text-sm text-[var(--foreground)]">
          {drivers !== null ? `${drivers} Fahrer` : '--'}
        </p>
        <p className="text-xs text-[var(--muted-foreground)]">{coverage}</p>
      </div>
      <span className="text-xs text-[var(--muted-foreground)] w-20 text-right">
        {updatedAt}
      </span>
    </div>
  );
}

interface QuickActionProps {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
}

function QuickAction({ href, icon: Icon, title, description }: QuickActionProps) {
  return (
    <Link
      href={href}
      className="flex items-center gap-3 p-3 rounded-md hover:bg-[var(--muted)] transition-colors group"
    >
      <div className="h-10 w-10 rounded-md bg-[var(--sv-primary)]/10 flex items-center justify-center group-hover:bg-[var(--sv-primary)]/20 transition-colors">
        <Icon className="h-5 w-5 text-[var(--sv-primary)]" />
      </div>
      <div>
        <p className="text-sm font-medium text-[var(--foreground)]">{title}</p>
        <p className="text-xs text-[var(--muted-foreground)]">{description}</p>
      </div>
    </Link>
  );
}

interface ActivityItemProps {
  action: string;
  details: string;
  time: string;
  type: 'success' | 'warning' | 'error' | 'info';
}

function ActivityItem({ action, details, time, type }: ActivityItemProps) {
  const colors = {
    success: 'bg-[var(--sv-success)]',
    warning: 'bg-[var(--sv-warning)]',
    error: 'bg-[var(--sv-error)]',
    info: 'bg-[var(--sv-info)]',
  };

  return (
    <div className="flex gap-3">
      <div className={`h-2 w-2 mt-2 rounded-full flex-shrink-0 ${colors[type]}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--foreground)]">{action}</p>
        <p className="text-xs text-[var(--muted-foreground)] truncate">{details}</p>
      </div>
      <span className="text-xs text-[var(--muted-foreground)] flex-shrink-0">
        {time}
      </span>
    </div>
  );
}
