"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import type { DashboardStatusFilter } from "@/lib/portal-types";
import { exportDriversCsv } from "@/lib/portal-api";
import { formatDate } from "@/lib/format";

interface ExportCsvButtonProps {
  snapshotId: string;
  filter: DashboardStatusFilter;
  weekStart?: string;
}

export function ExportCsvButton({ snapshotId, filter, weekStart }: ExportCsvButtonProps) {
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = async () => {
    setIsExporting(true);

    try {
      const result = await exportDriversCsv(snapshotId, filter);

      if ("error" in result) {
        console.error("Export failed:", result.error);
        return;
      }

      // Create download link
      const url = URL.createObjectURL(result);
      const link = document.createElement("a");
      link.href = url;
      link.download = `portal-export-${weekStart ? formatDate(weekStart).replace(/\./g, "-") : snapshotId.slice(0, 8)}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <button
      onClick={handleExport}
      disabled={isExporting}
      className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
    >
      {isExporting ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          Exportieren...
        </>
      ) : (
        <>
          <Download className="w-4 h-4" />
          CSV Export
        </>
      )}
    </button>
  );
}
