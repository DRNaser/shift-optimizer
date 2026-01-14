'use client';

import { useState, useEffect, useCallback, use } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Grid3x3,
  RefreshCw,
  Loader2,
  AlertCircle,
  Upload,
  Filter,
  Search,
  Lock,
  Unlock,
  GitCompare,
  Wrench,
  AlertTriangle,
} from 'lucide-react';
import {
  MatrixGrid,
  FixQueuePanel,
  CellDrawer,
  type MatrixData,
  type MatrixViolation,
  type CellData,
} from '@/components/roster';
import { generateIdempotencyKey } from '@/lib/security/idempotency';
import { isFeatureEnabled, canLock, canPublish as canPublishRole } from '@/lib/feature-flags';
import {
  parseMatrixResponse,
  parseViolationsResponse,
  parsePinsResponse,
} from '@/lib/schemas/matrix-schemas';

interface PageProps {
  params: Promise<{ id: string }>;
}

interface PlanInfo {
  id: number;
  plan_state: string;
  seed: number;
  current_snapshot_id: number | null;
  is_locked?: boolean;
  locked_at?: string;
  locked_by?: string;
}

export default function MatrixPage({ params }: PageProps) {
  const { id: planId } = use(params);
  const [planInfo, setPlanInfo] = useState<PlanInfo | null>(null);
  const [matrixData, setMatrixData] = useState<MatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // UI state
  const [searchQuery, setSearchQuery] = useState('');
  const [filterSeverity, setFilterSeverity] = useState<'ALL' | 'BLOCK' | 'WARN'>('ALL');
  const [selectedCell, setSelectedCell] = useState<{ driverId: string; day: string } | null>(null);
  const [drawerData, setDrawerData] = useState<CellData | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Lock modal state
  const [showLockModal, setShowLockModal] = useState(false);
  const [lockReason, setLockReason] = useState('');
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState<string | null>(null);

  // Feature flags
  const repairsEnabled = isFeatureEnabled('enableRepairs');
  const freezeEnabled = isFeatureEnabled('enableFreeze');
  // TODO: Get user role from auth context
  const userRole = 'dispatcher'; // Placeholder - should come from auth

  // Fetch plan info and matrix data
  const fetchData = useCallback(async () => {
    try {
      // Fetch plan info and matrix in parallel
      const [planRes, matrixRes, violationsRes, pinsRes] = await Promise.all([
        fetch(`/api/roster/plans/${planId}`),
        fetch(`/api/roster/plans/${planId}/matrix`),
        fetch(`/api/roster/plans/${planId}/violations`),
        fetch(`/api/roster/plans/${planId}/pins`),
      ]);

      if (!planRes.ok) {
        const err = await planRes.json();
        throw new Error(err.error || 'Failed to fetch plan');
      }

      const planData = await planRes.json();
      setPlanInfo(planData.plan);

      // Parse matrix response with Zod validation
      if (!matrixRes.ok) {
        const err = await matrixRes.json();
        throw new Error(err.error || 'Failed to fetch matrix');
      }

      // Zod-validated parsing with fallbacks for malformed data
      const matrixRaw = await matrixRes.json();
      const matrixValidated = parseMatrixResponse(matrixRaw);

      const violationsRaw = violationsRes.ok ? await violationsRes.json() : { violations: [] };
      const violationsValidated = parseViolationsResponse(violationsRaw);

      const pinsRaw = pinsRes.ok ? await pinsRes.json() : { pins: [] };
      const pinsValidated = parsePinsResponse(pinsRaw);

      // Merge pins into cells
      const pinMap = new Map<string, number>();
      pinsValidated.pins.forEach((pin) => {
        pinMap.set(`${pin.driver_id}:${pin.day}`, pin.id);
      });

      // Add violations to cells
      const violationMap = new Map<string, string[]>();
      const cellSeverityMap = new Map<string, 'BLOCK' | 'WARN'>();
      violationsValidated.violations.forEach((v) => {
        if (v.day) {
          const key = `${v.driver_id}:${v.day}`;
          if (!violationMap.has(key)) {
            violationMap.set(key, []);
          }
          violationMap.get(key)!.push(v.message);

          // Track worst severity per cell
          if (v.severity === 'BLOCK' || !cellSeverityMap.has(key)) {
            cellSeverityMap.set(key, v.severity);
          }
        }
      });

      // Transform cells to match component interface
      const enhancedCells = matrixValidated.cells.map((cell) => {
        const key = `${cell.driver_id}:${cell.day}`;
        const pinId = pinMap.get(key);
        const cellViolations = violationMap.get(key) || [];
        const severity = cellSeverityMap.get(key) || null;

        return {
          driver_id: cell.driver_id,
          day: cell.day,
          tour_instance_id: cell.tour_instance_id ?? null,
          tour_name: cell.block_type || null, // Map block_type to tour_name
          block_type: cell.block_type ?? null,
          start_time: null as string | null, // Backend may not provide
          end_time: null as string | null,
          hours: cell.work_hours ?? null,
          is_pinned: !!pinId || cell.is_pinned,
          pin_id: pinId ?? cell.pin_id ?? null,
          violations: cellViolations,
          severity: severity as 'BLOCK' | 'WARN' | 'OK' | null,
        };
      });

      // Calculate driver-level violation counts
      const driverBlockCounts = new Map<string, number>();
      const driverWarnCounts = new Map<string, number>();
      violationsValidated.violations.forEach((v) => {
        if (v.severity === 'BLOCK') {
          driverBlockCounts.set(v.driver_id, (driverBlockCounts.get(v.driver_id) || 0) + 1);
        } else {
          driverWarnCounts.set(v.driver_id, (driverWarnCounts.get(v.driver_id) || 0) + 1);
        }
      });

      // Transform drivers to match component interface
      const enhancedDrivers = matrixValidated.drivers.map((driver) => ({
        driver_id: driver.driver_id,
        driver_name: driver.driver_name,
        external_id: undefined as string | undefined,
        total_hours: driver.weekly_hours ?? 0,
        block_count: driverBlockCounts.get(driver.driver_id) || driver.block_count,
        warn_count: driverWarnCounts.get(driver.driver_id) || driver.warn_count,
      }));

      // Transform violations to match component interface
      const transformedViolations: MatrixViolation[] = violationsValidated.violations.map((v, idx) => ({
        id: String(v.id ?? `v-${idx}`),
        type: v.type,
        severity: v.severity,
        driver_id: v.driver_id,
        day: v.day ?? null,
        message: v.message,
        details: v.details,
      }));

      setMatrixData({
        drivers: enhancedDrivers,
        days: matrixValidated.days || ['mon', 'tue', 'wed', 'thu', 'fri', 'sat'],
        cells: enhancedCells,
        violations: transformedViolations,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [planId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleCellClick = (cellData: CellData) => {
    setSelectedCell({ driverId: cellData.driverId, day: cellData.day });
    setDrawerData(cellData);
    setIsDrawerOpen(true);
  };

  const handleViolationClick = (violation: MatrixViolation) => {
    if (violation.day && matrixData) {
      const driver = matrixData.drivers.find((d) => d.driver_id === violation.driver_id);
      const cell = matrixData.cells.find(
        (c) => c.driver_id === violation.driver_id && c.day === violation.day
      );
      if (driver && cell) {
        handleCellClick({
          driverId: driver.driver_id,
          driverName: driver.driver_name,
          day: violation.day,
          cell,
        });
      }
    }
  };

  const handleJumpToCell = (driverId: string, day: string) => {
    setSelectedCell({ driverId, day });
    // Could scroll to the cell here
  };

  const handlePinToggle = async (driverId: string, day: string, tourInstanceId: number | null) => {
    try {
      const existingPin = matrixData?.cells.find(
        (c) => c.driver_id === driverId && c.day === day
      )?.pin_id;

      if (existingPin) {
        // Unpin
        const res = await fetch(`/api/roster/plans/${planId}/pins/${existingPin}`, {
          method: 'DELETE',
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error || 'Failed to unpin');
        }
      } else {
        // Pin
        const idempotencyKey = generateIdempotencyKey('roster.pin.create', `${driverId}:${day}`);
        const res = await fetch(`/api/roster/plans/${planId}/pins`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-idempotency-key': idempotencyKey,
          },
          body: JSON.stringify({
            driver_id: driverId,
            day,
            tour_instance_id: tourInstanceId,
            reason_code: 'MANUAL',
            note: 'Pinned from matrix UI',
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error || 'Failed to pin');
        }
      }

      // Refresh data
      fetchData();
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Pin operation failed');
    }
  };

  const handlePin = (driverId: string, day: string, tourInstanceId: number | null) => {
    handlePinToggle(driverId, day, tourInstanceId);
    setIsDrawerOpen(false);
  };

  const handleUnpin = (pinId: number) => {
    const cell = matrixData?.cells.find((c) => c.pin_id === pinId);
    if (cell) {
      handlePinToggle(cell.driver_id, cell.day, cell.tour_instance_id);
    }
    setIsDrawerOpen(false);
  };

  // Lock handler - irreversible operation
  const handleLock = async () => {
    if (!planInfo || planInfo.is_locked) return;

    setLocking(true);
    setLockError(null);

    try {
      const res = await fetch(`/api/roster/plans/${planId}/lock`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          reason: lockReason || 'Locked via Matrix UI',
          confirm: true,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setLockError(data.error || `Lock failed: ${res.status}`);
        return;
      }

      // Update local state
      setPlanInfo((prev) => prev ? { ...prev, is_locked: true, locked_at: new Date().toISOString() } : null);
      setShowLockModal(false);
      setLockReason('');
    } catch (e) {
      setLockError(e instanceof Error ? e.message : 'Lock operation failed');
    } finally {
      setLocking(false);
    }
  };

  // Filter data based on search and severity filter
  const filteredData = matrixData
    ? {
        ...matrixData,
        drivers: matrixData.drivers.filter((driver) => {
          const matchesSearch =
            !searchQuery ||
            driver.driver_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            driver.driver_id.toLowerCase().includes(searchQuery.toLowerCase());

          const matchesFilter =
            filterSeverity === 'ALL' ||
            (filterSeverity === 'BLOCK' && driver.block_count > 0) ||
            (filterSeverity === 'WARN' && driver.warn_count > 0);

          return matchesSearch && matchesFilter;
        }),
      }
    : null;

  function getStateColor(state: string) {
    switch (state) {
      case 'PUBLISHED':
        return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
      case 'APPROVED':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'SOLVED':
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
      case 'DRAFT':
        return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
      default:
        return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 text-slate-400 animate-spin" />
          <p className="text-slate-400">Loading matrix...</p>
        </div>
      </div>
    );
  }

  if (error || !matrixData) {
    return (
      <div className="min-h-screen bg-slate-900 p-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 flex items-center gap-3 text-red-400">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <p>{error || 'Failed to load matrix data'}</p>
          </div>
        </div>
      </div>
    );
  }

  const blockCount = matrixData.violations.filter((v) => v.severity === 'BLOCK').length;
  const warnCount = matrixData.violations.filter((v) => v.severity === 'WARN').length;
  const isLocked = planInfo?.is_locked ?? false;
  const canPublishPlan = blockCount === 0 && planInfo?.plan_state !== 'PUBLISHED' && !isLocked && canPublishRole(userRole);
  const canLockPlan = freezeEnabled && canLock(userRole) && planInfo?.plan_state === 'PUBLISHED' && !isLocked;
  const canRepair = repairsEnabled && !isLocked;

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      {/* Header */}
      <div className="border-b border-slate-800 bg-slate-900/80 sticky top-0 z-30">
        <div className="px-6 py-4">
          <div className="flex items-center gap-4">
            <Link
              href={`/packs/roster/plans/${planId}`}
              className="text-slate-400 hover:text-slate-200 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <Grid3x3 className="w-6 h-6 text-slate-500" />
                <h1 className="text-xl font-bold text-white">Roster Matrix</h1>
                {planInfo && (
                  <>
                    <span className="text-slate-500">Plan #{planInfo.id}</span>
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${getStateColor(
                        planInfo.plan_state
                      )}`}
                    >
                      {planInfo.plan_state}
                    </span>
                    <span className="text-slate-600 text-sm">Seed: {planInfo.seed}</span>
                  </>
                )}
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* Lock Status Indicator */}
              {isLocked && (
                <span className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
                  <Lock className="w-3.5 h-3.5" />
                  Locked {planInfo?.locked_at && `(${new Date(planInfo.locked_at).toLocaleDateString('de-AT')})`}
                </span>
              )}

              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="flex items-center gap-2 px-3 py-2 text-sm text-slate-400 hover:text-white border border-slate-700 rounded-lg hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                Refresh
              </button>

              {/* Diff Link */}
              <Link
                href={`/packs/roster/plans/${planId}/diff`}
                className="flex items-center gap-2 px-3 py-2 text-sm text-slate-400 hover:text-white border border-slate-700 rounded-lg hover:bg-slate-800 transition-colors"
              >
                <GitCompare className="w-4 h-4" />
                Diff
              </Link>

              {/* Repair Mode - gated by feature flag */}
              {canRepair ? (
                <Link
                  href={`/packs/roster/repair?plan_id=${planId}`}
                  className="flex items-center gap-2 px-3 py-2 text-sm text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
                >
                  <Wrench className="w-4 h-4" />
                  Repair Mode
                </Link>
              ) : isLocked ? (
                <span className="flex items-center gap-2 px-3 py-2 text-sm text-slate-500 bg-slate-800 rounded-lg cursor-not-allowed" title="Plan is locked - repairs not allowed">
                  <Wrench className="w-4 h-4" />
                  Repair Mode
                </span>
              ) : !repairsEnabled ? (
                <span className="flex items-center gap-2 px-3 py-2 text-sm text-slate-500 bg-slate-800 rounded-lg cursor-not-allowed" title="Repairs feature is disabled">
                  <Wrench className="w-4 h-4" />
                  Repairs Disabled
                </span>
              ) : null}

              {/* Publish Button */}
              {canPublishPlan && (
                <Link
                  href={`/packs/roster/plans/${planId}#publish`}
                  className="flex items-center gap-2 px-3 py-2 text-sm text-white bg-emerald-600 hover:bg-emerald-500 rounded-lg transition-colors"
                >
                  <Upload className="w-4 h-4" />
                  Publish
                </Link>
              )}

              {/* Lock Button - only shown for published plans that aren't locked */}
              {canLockPlan && (
                <button
                  onClick={() => setShowLockModal(true)}
                  className="flex items-center gap-2 px-3 py-2 text-sm text-white bg-amber-600 hover:bg-amber-500 rounded-lg transition-colors"
                  title="Lock plan (irreversible)"
                >
                  <Lock className="w-4 h-4" />
                  Lock
                </button>
              )}
            </div>
          </div>

          {/* Toolbar */}
          <div className="flex items-center gap-4 mt-4">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                type="text"
                placeholder="Search drivers..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-slate-600"
              />
            </div>

            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-500" />
              <select
                value={filterSeverity}
                onChange={(e) => setFilterSeverity(e.target.value as typeof filterSeverity)}
                className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-slate-600"
              >
                <option value="ALL">All Drivers</option>
                <option value="BLOCK">With Blockers</option>
                <option value="WARN">With Warnings</option>
              </select>
            </div>

            <div className="flex items-center gap-3 ml-auto">
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                <AlertCircle className="w-3.5 h-3.5" />
                {blockCount} Blockers
              </span>
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
                {warnCount} Warnings
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex">
        {/* Matrix Grid */}
        <div className="flex-1 p-6 overflow-auto">
          {filteredData && (
            <MatrixGrid
              data={filteredData}
              onCellClick={handleCellClick}
              onPinToggle={handlePinToggle}
              selectedCell={selectedCell}
            />
          )}
        </div>

        {/* Fix Queue Sidebar */}
        <div className="w-80 border-l border-slate-800 bg-slate-900/50 shrink-0">
          <FixQueuePanel
            violations={matrixData.violations}
            onViolationClick={handleViolationClick}
            onJumpToCell={handleJumpToCell}
          />
        </div>
      </div>

      {/* Cell Drawer */}
      <CellDrawer
        data={drawerData}
        isOpen={isDrawerOpen}
        onClose={() => {
          setIsDrawerOpen(false);
          setSelectedCell(null);
        }}
        onPin={handlePin}
        onUnpin={handleUnpin}
        onRepairStart={(driverId, day) => {
          window.location.href = `/packs/roster/repair?plan_id=${planId}&driver_id=${driverId}&day=${day}`;
        }}
      />

      {/* Lock Confirmation Modal */}
      {showLockModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-400" />
              </div>
              <h3 className="text-lg font-semibold text-white">Lock Plan</h3>
            </div>

            <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 mb-4">
              <p className="text-sm text-amber-300 font-medium">Warning: This action is irreversible</p>
              <p className="text-xs text-amber-400/80 mt-1">
                Once locked, this plan cannot be modified or repaired. This is required for arbeitsrechtlich compliance.
              </p>
            </div>

            <div className="mb-4">
              <label className="block text-sm text-slate-400 mb-2">Lock Reason (optional)</label>
              <input
                type="text"
                value={lockReason}
                onChange={(e) => setLockReason(e.target.value)}
                placeholder="e.g., Week finalized, approved by ops"
                className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-amber-500"
              />
            </div>

            {lockError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 mb-4 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
                <p className="text-sm text-red-400">{lockError}</p>
              </div>
            )}

            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowLockModal(false);
                  setLockReason('');
                  setLockError(null);
                }}
                disabled={locking}
                className="flex-1 px-4 py-2 text-sm text-slate-300 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleLock}
                disabled={locking}
                className="flex-1 px-4 py-2 text-sm text-white bg-amber-600 hover:bg-amber-500 rounded-lg transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {locking ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Locking...
                  </>
                ) : (
                  <>
                    <Lock className="w-4 h-4" />
                    Confirm Lock
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
