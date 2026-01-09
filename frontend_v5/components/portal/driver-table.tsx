"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Mail,
  MessageCircle,
  Smartphone,
  MoreHorizontal,
} from "lucide-react";
import type { DriverStatus, SortState } from "@/lib/portal-types";
import {
  formatDateTime,
  formatHours,
  getOverallStatusLabel,
  getStatusColor,
  getAckStatusLabel,
  getAckStatusColor,
  getSkippedReasonLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

interface DriverTableProps {
  drivers: DriverStatus[];
  isLoading?: boolean;
  onDriverClick?: (driver: DriverStatus) => void;
  selectedDriverIds?: string[];
  onSelectionChange?: (driverIds: string[]) => void;
}

const COLUMNS: Array<{
  key: keyof DriverStatus | "actions";
  label: string;
  sortable: boolean;
  width?: string;
}> = [
  { key: "driver_name", label: "Fahrer", sortable: true, width: "w-48" },
  { key: "overall_status", label: "Status", sortable: true, width: "w-32" },
  { key: "delivery_channel", label: "Kanal", sortable: true, width: "w-24" },
  { key: "issued_at", label: "Gesendet", sortable: true, width: "w-36" },
  { key: "read_at", label: "Gelesen", sortable: true, width: "w-36" },
  { key: "ack_status", label: "Bestätigung", sortable: true, width: "w-28" },
  { key: "total_hours", label: "Stunden", sortable: true, width: "w-24" },
  { key: "actions", label: "", sortable: false, width: "w-12" },
];

function ChannelIcon({ channel }: { channel: string | null }) {
  if (!channel) return <Mail className="w-4 h-4 text-slate-500" />;
  switch (channel) {
    case "EMAIL":
      return <Mail className="w-4 h-4 text-slate-400" />;
    case "WHATSAPP":
      return <MessageCircle className="w-4 h-4 text-emerald-400" />;
    case "SMS":
      return <Smartphone className="w-4 h-4 text-blue-400" />;
    default:
      return <Mail className="w-4 h-4 text-slate-500" />;
  }
}

export function DriverTable({
  drivers,
  isLoading = false,
  onDriverClick,
  selectedDriverIds = [],
  onSelectionChange,
}: DriverTableProps) {
  const [sort, setSort] = useState<SortState>({ field: null, direction: "asc" });

  const handleSort = (field: keyof DriverStatus) => {
    setSort((prev) => ({
      field,
      direction: prev.field === field && prev.direction === "asc" ? "desc" : "asc",
    }));
  };

  const sortedDrivers = [...drivers].sort((a, b) => {
    if (!sort.field) return 0;
    const aVal = a[sort.field];
    const bVal = b[sort.field];
    if (aVal === null || aVal === undefined) return 1;
    if (bVal === null || bVal === undefined) return -1;
    if (aVal < bVal) return sort.direction === "asc" ? -1 : 1;
    if (aVal > bVal) return sort.direction === "asc" ? 1 : -1;
    return 0;
  });

  const toggleSelection = (driverId: string) => {
    if (!onSelectionChange) return;
    const newSelection = selectedDriverIds.includes(driverId)
      ? selectedDriverIds.filter((id) => id !== driverId)
      : [...selectedDriverIds, driverId];
    onSelectionChange(newSelection);
  };

  const toggleAll = () => {
    if (!onSelectionChange) return;
    if (selectedDriverIds.length === drivers.length) {
      onSelectionChange([]);
    } else {
      onSelectionChange(drivers.map((d) => d.driver_id));
    }
  };

  if (isLoading) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="p-4 space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (drivers.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-8 text-center">
        <p className="text-slate-500">Keine Fahrer gefunden</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-800/50">
              {onSelectionChange && (
                <th className="px-4 py-3 w-12">
                  <input
                    type="checkbox"
                    checked={selectedDriverIds.length === drivers.length}
                    onChange={toggleAll}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500/20"
                  />
                </th>
              )}
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    "px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider",
                    col.width,
                    col.sortable && "cursor-pointer hover:text-slate-400"
                  )}
                  onClick={() =>
                    col.sortable &&
                    col.key !== "actions" &&
                    handleSort(col.key as keyof DriverStatus)
                  }
                >
                  <div className="flex items-center gap-1">
                    {col.label}
                    {col.sortable && sort.field === col.key && (
                      sort.direction === "asc" ? (
                        <ChevronUp className="w-4 h-4" />
                      ) : (
                        <ChevronDown className="w-4 h-4" />
                      )
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {sortedDrivers.map((driver) => (
              <tr
                key={driver.driver_id}
                className="hover:bg-slate-800/50 transition-colors cursor-pointer"
                onClick={() => onDriverClick?.(driver)}
              >
                {onSelectionChange && (
                  <td
                    className="px-4 py-3"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelection(driver.driver_id);
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedDriverIds.includes(driver.driver_id)}
                      onChange={() => toggleSelection(driver.driver_id)}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500/20"
                    />
                  </td>
                )}
                <td className="px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-white">
                      {driver.driver_name}
                    </p>
                    <p className="text-xs text-slate-500">{driver.driver_id}</p>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="space-y-1">
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-1 rounded-full text-xs font-medium",
                        getStatusColor(driver.overall_status)
                      )}
                    >
                      {getOverallStatusLabel(driver.overall_status)}
                    </span>
                    {driver.overall_status === "SKIPPED" && driver.skip_reason && (
                      <p className="text-xs text-orange-400/80 truncate max-w-[120px]" title={getSkippedReasonLabel(driver.skip_reason)}>
                        {getSkippedReasonLabel(driver.skip_reason)}
                      </p>
                    )}
                    {driver.overall_status === "FAILED" && driver.error_message && (
                      <p className="text-xs text-red-400/80 truncate max-w-[120px]" title={driver.error_message}>
                        {driver.error_message}
                      </p>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <ChannelIcon channel={driver.delivery_channel} />
                </td>
                <td className="px-4 py-3 text-sm text-slate-400">
                  {formatDateTime(driver.issued_at)}
                </td>
                <td className="px-4 py-3 text-sm text-slate-400">
                  {formatDateTime(driver.read_at)}
                </td>
                <td className="px-4 py-3">
                  {driver.ack_status && (
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-1 rounded-full text-xs font-medium",
                        getAckStatusColor(driver.ack_status)
                      )}
                    >
                      {getAckStatusLabel(driver.ack_status)}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-sm text-slate-400">
                  {formatHours(driver.total_hours)}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDriverClick?.(driver);
                    }}
                    className="p-1 hover:bg-slate-700 rounded transition-colors"
                  >
                    <MoreHorizontal className="w-4 h-4 text-slate-500" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
