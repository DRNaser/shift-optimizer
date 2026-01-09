"use client";

import {
  Users,
  Send,
  Eye,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Ban,
} from "lucide-react";
import type { DashboardKPIs } from "@/lib/portal-types";
import { formatPercent } from "@/lib/format";

interface PortalKpiCardsProps {
  kpis: DashboardKPIs;
  isLoading?: boolean;
}

export function PortalKpiCards({ kpis, isLoading = false }: PortalKpiCardsProps) {
  const cards = [
    {
      label: "Gesamt",
      value: kpis.total,
      format: (v: number) => v.toString(),
      icon: Users,
      color: "text-slate-400",
      bgColor: "bg-slate-500/10",
    },
    {
      label: "Zugestellt",
      value: kpis.delivered,
      format: (v: number) => v.toString(),
      icon: Send,
      color: "text-cyan-400",
      bgColor: "bg-cyan-500/10",
      subtitle: formatPercent(kpis.deliveryRate, 1),
    },
    {
      label: "Gelesen",
      value: kpis.read,
      format: (v: number) => v.toString(),
      icon: Eye,
      color: "text-purple-400",
      bgColor: "bg-purple-500/10",
      subtitle: formatPercent(kpis.readRate, 1),
    },
    {
      label: "Akzeptiert",
      value: kpis.accepted,
      format: (v: number) => v.toString(),
      icon: CheckCircle,
      color: "text-emerald-400",
      bgColor: "bg-emerald-500/10",
    },
    {
      label: "Abgelehnt",
      value: kpis.declined,
      format: (v: number) => v.toString(),
      icon: XCircle,
      color: "text-amber-400",
      bgColor: "bg-amber-500/10",
    },
    {
      label: "Übersprungen",
      value: kpis.skipped,
      format: (v: number) => v.toString(),
      icon: Ban,
      color: "text-orange-400",
      bgColor: "bg-orange-500/10",
    },
    {
      label: "Fehlgeschlagen",
      value: kpis.failed,
      format: (v: number) => v.toString(),
      icon: AlertTriangle,
      color: "text-red-400",
      bgColor: "bg-red-500/10",
    },
  ];

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
        {cards.map((_, i) => (
          <div
            key={i}
            className="bg-slate-900 border border-slate-800 rounded-lg p-4 animate-pulse"
          >
            <div className="h-4 bg-slate-800 rounded w-20 mb-3" />
            <div className="h-8 bg-slate-800 rounded w-12" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-slate-900 border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors"
        >
          <div className="flex items-center gap-2 mb-2">
            <div className={`p-1.5 rounded ${card.bgColor}`}>
              <card.icon className={`w-4 h-4 ${card.color}`} />
            </div>
            <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
              {card.label}
            </span>
          </div>
          <div className={`text-2xl font-bold ${card.color}`}>
            {card.format(card.value)}
          </div>
          {card.subtitle && (
            <div className="text-xs text-slate-500 mt-1">{card.subtitle}</div>
          )}
        </div>
      ))}
    </div>
  );
}
