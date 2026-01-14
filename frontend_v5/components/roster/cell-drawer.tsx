'use client';

import { X, Pin, PinOff, AlertCircle, AlertTriangle, Clock, User, MapPin, Repeat, ArrowRight, Calendar } from 'lucide-react';
import type { CellData } from './shift-cell';

interface CellDrawerProps {
  data: CellData | null;
  isOpen: boolean;
  onClose: () => void;
  onPin?: (driverId: string, day: string, tourInstanceId: number | null) => void;
  onUnpin?: (pinId: number) => void;
  onRepairStart?: (driverId: string, day: string) => void;
}

const DAY_LABELS: Record<string, string> = {
  mon: 'Monday',
  tue: 'Tuesday',
  wed: 'Wednesday',
  thu: 'Thursday',
  fri: 'Friday',
  sat: 'Saturday',
  sun: 'Sunday',
};

export function CellDrawer({
  data,
  isOpen,
  onClose,
  onPin,
  onUnpin,
  onRepairStart,
}: CellDrawerProps) {
  if (!isOpen || !data) return null;

  const { driverId, driverName, day, cell } = data;
  const isEmpty = !cell.tour_name && !cell.block_type;
  const hasViolations = cell.violations.length > 0;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 bottom-0 w-96 bg-slate-900 border-l border-slate-800 z-50 flex flex-col shadow-xl">
        {/* Header */}
        <div className="px-4 py-4 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">Cell Details</h2>
            <p className="text-sm text-slate-500">
              {driverName} &middot; {DAY_LABELS[day] || day}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Assignment Info */}
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
              <Calendar className="w-4 h-4" />
              Assignment
            </h3>
            {isEmpty ? (
              <div className="text-center py-4">
                <div className="w-12 h-12 rounded-full bg-slate-700/50 flex items-center justify-center mx-auto mb-2">
                  <User className="w-6 h-6 text-slate-500" />
                </div>
                <p className="text-slate-400 text-sm">No assignment</p>
                <p className="text-slate-600 text-xs mt-1">This driver is off on this day</p>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 text-sm">Tour</span>
                  <span className="text-white font-medium">{cell.tour_name || '-'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 text-sm">Block Type</span>
                  <span className="text-slate-300 font-mono text-sm">{cell.block_type || '-'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 text-sm">Time</span>
                  <span className="text-slate-300">
                    {cell.start_time && cell.end_time
                      ? `${cell.start_time.slice(0, 5)} - ${cell.end_time.slice(0, 5)}`
                      : '-'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 text-sm">Hours</span>
                  <span className="text-emerald-400 font-mono">
                    {cell.hours ? `${cell.hours.toFixed(1)}h` : '-'}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Pin Status */}
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
              <Pin className="w-4 h-4" />
              Pin Status
            </h3>
            {cell.is_pinned ? (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-full bg-purple-500/20 flex items-center justify-center">
                    <Pin className="w-4 h-4 text-purple-400" />
                  </div>
                  <div>
                    <p className="text-sm text-white">Pinned</p>
                    <p className="text-xs text-slate-500">Will not be changed by solver</p>
                  </div>
                </div>
                {onUnpin && cell.pin_id && (
                  <button
                    onClick={() => onUnpin(cell.pin_id!)}
                    className="px-3 py-1.5 text-xs font-medium text-purple-400 border border-purple-500/30 rounded-lg hover:bg-purple-500/10 transition-colors flex items-center gap-1"
                  >
                    <PinOff className="w-3.5 h-3.5" />
                    Unpin
                  </button>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-full bg-slate-700/50 flex items-center justify-center">
                    <PinOff className="w-4 h-4 text-slate-500" />
                  </div>
                  <div>
                    <p className="text-sm text-slate-400">Not pinned</p>
                    <p className="text-xs text-slate-600">Can be modified by solver</p>
                  </div>
                </div>
                {onPin && !isEmpty && (
                  <button
                    onClick={() => onPin(driverId, day, cell.tour_instance_id)}
                    className="px-3 py-1.5 text-xs font-medium text-slate-400 border border-slate-600 rounded-lg hover:bg-slate-700 transition-colors flex items-center gap-1"
                  >
                    <Pin className="w-3.5 h-3.5" />
                    Pin
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Violations */}
          {hasViolations && (
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
              <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
                <AlertCircle className="w-4 h-4" />
                Violations ({cell.violations.length})
              </h3>
              <div className="space-y-2">
                {cell.violations.map((v, idx) => (
                  <div
                    key={idx}
                    className={`flex items-start gap-2 p-2 rounded-lg ${
                      cell.severity === 'BLOCK'
                        ? 'bg-red-500/10 border border-red-500/20'
                        : 'bg-amber-500/10 border border-amber-500/20'
                    }`}
                  >
                    {cell.severity === 'BLOCK' ? (
                      <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                    ) : (
                      <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    )}
                    <span className="text-sm text-slate-300">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Quick Actions */}
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3">Quick Actions</h3>
            <div className="space-y-2">
              {onRepairStart && (
                <button
                  onClick={() => onRepairStart(driverId, day)}
                  className="w-full px-4 py-2.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors flex items-center justify-center gap-2"
                >
                  <Repeat className="w-4 h-4" />
                  Start Repair
                  <ArrowRight className="w-4 h-4 ml-auto" />
                </button>
              )}
              <button
                disabled
                className="w-full px-4 py-2.5 text-sm font-medium text-slate-500 bg-slate-800 rounded-lg cursor-not-allowed flex items-center justify-center gap-2"
              >
                <MapPin className="w-4 h-4" />
                Swap Driver (Coming Soon)
              </button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-slate-800 bg-slate-900/50">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Driver: {driverId}</span>
            {cell.tour_instance_id && <span>Tour #{cell.tour_instance_id}</span>}
          </div>
        </div>
      </div>
    </>
  );
}
