"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { RefreshCw, ChevronDown, Loader2 } from "lucide-react";
import {
  PortalKpiCards,
  StatusFilters,
  DriverTable,
  DriverDrawer,
  ResendDialog,
  ExportCsvButton,
} from "@/components/portal";
import {
  fetchDashboardSummary,
  fetchDriverList,
  triggerResend,
  fetchSnapshots,
  calculateKPIs,
} from "@/lib/portal-api";
import type {
  DashboardStatusFilter,
  DashboardKPIs,
  DriverStatus,
  SnapshotSummary,
  ResendRequest,
  DrawerState,
} from "@/lib/portal-types";
import { formatWeekRange } from "@/lib/format";
import { cn } from "@/lib/utils";

// =============================================================================
// DISPATCHER DASHBOARD PAGE
// =============================================================================
// RBAC: Requires Dispatcher or Approver role (enforced by BFF routes)
// =============================================================================

interface Snapshot {
  id: string;
  week_start: string;
  created_at: string;
}

export default function PortalDashboardPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // State
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(
    searchParams.get("snapshot_id")
  );
  const [summary, setSummary] = useState<SnapshotSummary | null>(null);
  const [drivers, setDrivers] = useState<DriverStatus[]>([]);
  const [kpis, setKpis] = useState<DashboardKPIs | null>(null);
  const [filter, setFilter] = useState<DashboardStatusFilter>("ALL");
  const [selectedDriverIds, setSelectedDriverIds] = useState<string[]>([]);
  const [drawer, setDrawer] = useState<DrawerState>({ isOpen: false, driver: null });
  const [showResendDialog, setShowResendDialog] = useState(false);
  const [isFilterResend, setIsFilterResend] = useState(false);

  // Loading states
  const [isLoadingSnapshots, setIsLoadingSnapshots] = useState(true);
  const [isLoadingData, setIsLoadingData] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Dropdown state
  const [showSnapshotDropdown, setShowSnapshotDropdown] = useState(false);

  // Load snapshots on mount
  useEffect(() => {
    const loadSnapshots = async () => {
      setIsLoadingSnapshots(true);
      const result = await fetchSnapshots();
      if ("snapshots" in result) {
        setSnapshots(result.snapshots);
        // Auto-select first snapshot if none selected
        if (!selectedSnapshotId && result.snapshots.length > 0) {
          setSelectedSnapshotId(result.snapshots[0].id);
        }
      }
      setIsLoadingSnapshots(false);
    };
    loadSnapshots();
  }, []);

  // Load data when snapshot changes
  useEffect(() => {
    if (!selectedSnapshotId) return;

    const loadData = async () => {
      setIsLoadingData(true);

      // Update URL
      router.replace(`/portal-admin/dashboard?snapshot_id=${selectedSnapshotId}`, {
        scroll: false,
      });

      // Fetch summary and details in parallel
      const [summaryResult, detailsResult] = await Promise.all([
        fetchDashboardSummary(selectedSnapshotId),
        fetchDriverList(selectedSnapshotId, "ALL", 1, 1000),
      ]);

      if ("summary" in summaryResult) {
        setSummary(summaryResult.summary);
      }

      if ("drivers" in detailsResult) {
        setDrivers(detailsResult.drivers);
        setKpis(calculateKPIs(detailsResult.drivers));
      }

      setIsLoadingData(false);
    };

    loadData();
  }, [selectedSnapshotId, router]);

  // Refresh data
  const handleRefresh = useCallback(async () => {
    if (!selectedSnapshotId || isRefreshing) return;

    setIsRefreshing(true);
    const [summaryResult, detailsResult] = await Promise.all([
      fetchDashboardSummary(selectedSnapshotId),
      fetchDriverList(selectedSnapshotId, "ALL", 1, 1000),
    ]);

    if ("summary" in summaryResult) {
      setSummary(summaryResult.summary);
    }

    if ("drivers" in detailsResult) {
      setDrivers(detailsResult.drivers);
      setKpis(calculateKPIs(detailsResult.drivers));
    }

    setIsRefreshing(false);
  }, [selectedSnapshotId, isRefreshing]);

  // Filter drivers for display
  const filteredDrivers = drivers.filter((d) => {
    switch (filter) {
      case "UNREAD":
        return d.delivered_at && !d.read_at;
      case "UNACKED":
        return d.read_at && !d.ack_status;
      case "ACCEPTED":
        return d.ack_status === "ACCEPTED";
      case "DECLINED":
        return d.ack_status === "DECLINED";
      case "SKIPPED":
        return d.overall_status === "SKIPPED";
      case "FAILED":
        return d.overall_status === "FAILED";
      default:
        return true;
    }
  });

  // Handle resend
  const handleResend = useCallback(
    async (reason?: string) => {
      if (!selectedSnapshotId) {
        return { success: false, queued_count: 0, skipped_count: 0, error: "Kein Snapshot ausgewählt" };
      }

      const request: ResendRequest = {
        snapshot_id: selectedSnapshotId,
        filter: isFilterResend ? filter : "ALL",
        driver_ids: isFilterResend ? undefined : selectedDriverIds,
      };

      // Add guardrail fields for DECLINED/SKIPPED
      if (filter === "DECLINED" && reason) {
        request.include_declined = true;
        request.declined_reason = reason;
      }
      if (filter === "SKIPPED" && reason) {
        request.include_skipped = true;
        request.skipped_reason = reason;
      }

      const result = await triggerResend(request);

      if (result.success) {
        // Refresh data after successful resend
        handleRefresh();
        setSelectedDriverIds([]);
      }

      return result;
    },
    [selectedSnapshotId, filter, isFilterResend, selectedDriverIds, handleRefresh]
  );

  // Open resend dialog
  const openResendDialog = (byFilter: boolean) => {
    setIsFilterResend(byFilter);
    setShowResendDialog(true);
  };

  // Get selected snapshot
  const selectedSnapshot = snapshots.find((s) => s.id === selectedSnapshotId);

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="sticky top-0 z-20 bg-slate-900/95 border-b border-slate-800 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h1 className="text-xl font-bold text-white">Portal Dashboard</h1>

              {/* Snapshot Selector */}
              <div className="relative">
                <button
                  onClick={() => setShowSnapshotDropdown(!showSnapshotDropdown)}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-sm text-white transition-colors"
                >
                  {isLoadingSnapshots ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : selectedSnapshot ? (
                    formatWeekRange(selectedSnapshot.week_start, null)
                  ) : (
                    "Snapshot wählen"
                  )}
                  <ChevronDown className="w-4 h-4" />
                </button>

                {showSnapshotDropdown && (
                  <>
                    <div
                      className="fixed inset-0 z-10"
                      onClick={() => setShowSnapshotDropdown(false)}
                    />
                    <div className="absolute top-full left-0 mt-2 w-64 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-20 overflow-hidden">
                      <div className="max-h-64 overflow-y-auto">
                        {snapshots.map((s) => (
                          <button
                            key={s.id}
                            onClick={() => {
                              setSelectedSnapshotId(s.id);
                              setShowSnapshotDropdown(false);
                            }}
                            className={cn(
                              "w-full px-4 py-3 text-left text-sm hover:bg-slate-700 transition-colors",
                              s.id === selectedSnapshotId
                                ? "bg-blue-500/20 text-blue-400"
                                : "text-white"
                            )}
                          >
                            <p className="font-medium">
                              {formatWeekRange(s.week_start, null)}
                            </p>
                            <p className="text-xs text-slate-500">{s.id.slice(0, 8)}</p>
                          </button>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3">
              <button
                onClick={handleRefresh}
                disabled={isRefreshing || !selectedSnapshotId}
                className="inline-flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white rounded-lg text-sm transition-colors disabled:opacity-50"
              >
                <RefreshCw
                  className={cn("w-4 h-4", isRefreshing && "animate-spin")}
                />
                Aktualisieren
              </button>

              {selectedSnapshotId && kpis && (
                <ExportCsvButton
                  snapshotId={selectedSnapshotId}
                  filter={filter}
                  weekStart={selectedSnapshot?.week_start}
                />
              )}

              {/* Resend Actions */}
              {selectedDriverIds.length > 0 && (
                <button
                  onClick={() => openResendDialog(false)}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {selectedDriverIds.length} erneut senden
                </button>
              )}
              {filter !== "ALL" && filteredDrivers.length > 0 && (
                <button
                  onClick={() => openResendDialog(true)}
                  className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  Alle {filter} erneut senden
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* KPI Cards */}
        <PortalKpiCards
          kpis={
            kpis || {
              total: 0,
              issued: 0,
              delivered: 0,
              read: 0,
              accepted: 0,
              declined: 0,
              skipped: 0,
              failed: 0,
              deliveryRate: 0,
              readRate: 0,
              ackRate: 0,
            }
          }
          isLoading={isLoadingData}
        />

        {/* Filters */}
        <StatusFilters
          activeFilter={filter}
          onFilterChange={(f) => {
            setFilter(f);
            setSelectedDriverIds([]);
          }}
          counts={kpis || undefined}
        />

        {/* Driver Table */}
        <DriverTable
          drivers={filteredDrivers}
          isLoading={isLoadingData}
          onDriverClick={(driver) => setDrawer({ isOpen: true, driver })}
          selectedDriverIds={selectedDriverIds}
          onSelectionChange={setSelectedDriverIds}
        />
      </main>

      {/* Driver Drawer */}
      <DriverDrawer
        driver={drawer.driver}
        isOpen={drawer.isOpen}
        onClose={() => setDrawer({ isOpen: false, driver: null })}
        onResend={(driverId) => {
          setSelectedDriverIds([driverId]);
          setIsFilterResend(false);
          setShowResendDialog(true);
        }}
      />

      {/* Resend Dialog */}
      <ResendDialog
        isOpen={showResendDialog}
        onClose={() => setShowResendDialog(false)}
        onConfirm={handleResend}
        filter={filter}
        selectedCount={isFilterResend ? filteredDrivers.length : selectedDriverIds.length}
        isFilterMode={isFilterResend}
      />
    </div>
  );
}
