"use client";

import { cn } from "@/lib/utils";
import type { DashboardStatusFilter, DashboardKPIs } from "@/lib/portal-types";
import { getFilterLabel } from "@/lib/format";

interface StatusFiltersProps {
  activeFilter: DashboardStatusFilter;
  onFilterChange: (filter: DashboardStatusFilter) => void;
  counts?: DashboardKPIs;
}

const FILTERS: DashboardStatusFilter[] = [
  "ALL",
  "UNREAD",
  "UNACKED",
  "ACCEPTED",
  "DECLINED",
  "SKIPPED",
  "FAILED",
];

export function StatusFilters({
  activeFilter,
  onFilterChange,
  counts,
}: StatusFiltersProps) {
  const getCount = (filter: DashboardStatusFilter): number | undefined => {
    if (!counts) return undefined;
    switch (filter) {
      case "ALL":
        return counts.total;
      case "UNREAD":
        return counts.delivered - counts.read;
      case "UNACKED":
        return counts.read - counts.accepted - counts.declined;
      case "ACCEPTED":
        return counts.accepted;
      case "DECLINED":
        return counts.declined;
      case "SKIPPED":
        return counts.skipped;
      case "FAILED":
        return counts.failed;
      default:
        return undefined;
    }
  };

  const getColorClass = (filter: DashboardStatusFilter): string => {
    switch (filter) {
      case "ACCEPTED":
        return "data-[active=true]:bg-emerald-500/20 data-[active=true]:border-emerald-500/50 data-[active=true]:text-emerald-400";
      case "DECLINED":
        return "data-[active=true]:bg-amber-500/20 data-[active=true]:border-amber-500/50 data-[active=true]:text-amber-400";
      case "SKIPPED":
        return "data-[active=true]:bg-orange-500/20 data-[active=true]:border-orange-500/50 data-[active=true]:text-orange-400";
      case "FAILED":
        return "data-[active=true]:bg-red-500/20 data-[active=true]:border-red-500/50 data-[active=true]:text-red-400";
      default:
        return "data-[active=true]:bg-blue-500/20 data-[active=true]:border-blue-500/50 data-[active=true]:text-blue-400";
    }
  };

  return (
    <div className="flex flex-wrap gap-2">
      {FILTERS.map((filter) => {
        const count = getCount(filter);
        const isActive = activeFilter === filter;

        return (
          <button
            key={filter}
            onClick={() => onFilterChange(filter)}
            data-active={isActive}
            className={cn(
              "inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium",
              "border border-slate-700 bg-slate-800/50 text-slate-400",
              "hover:bg-slate-800 hover:border-slate-600 transition-colors",
              getColorClass(filter)
            )}
          >
            <span>{getFilterLabel(filter)}</span>
            {count !== undefined && (
              <span
                className={cn(
                  "inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-xs",
                  isActive
                    ? "bg-white/10"
                    : "bg-slate-700/50 text-slate-500"
                )}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
