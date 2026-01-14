'use client';

import { useState } from 'react';
import { AlertCircle, AlertTriangle, ChevronRight, MapPin } from 'lucide-react';
import type { MatrixViolation } from './matrix-grid';

interface FixQueuePanelProps {
  violations: MatrixViolation[];
  onViolationClick?: (violation: MatrixViolation) => void;
  onJumpToCell?: (driverId: string, day: string) => void;
}

type TabType = 'BLOCK' | 'WARN';

export function FixQueuePanel({
  violations,
  onViolationClick,
  onJumpToCell,
}: FixQueuePanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('BLOCK');

  const blockers = violations.filter((v) => v.severity === 'BLOCK');
  const warnings = violations.filter((v) => v.severity === 'WARN');
  const filteredViolations = activeTab === 'BLOCK' ? blockers : warnings;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80">
        <h3 className="text-sm font-semibold text-white">Fix Queue</h3>
        <p className="text-xs text-slate-500 mt-1">
          Resolve blockers before publishing
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800">
        <button
          className={`flex-1 px-4 py-2 text-xs font-medium flex items-center justify-center gap-2 transition-colors ${
            activeTab === 'BLOCK'
              ? 'text-red-400 border-b-2 border-red-400 bg-red-500/5'
              : 'text-slate-500 hover:text-slate-300'
          }`}
          onClick={() => setActiveTab('BLOCK')}
        >
          <AlertCircle className="w-3.5 h-3.5" />
          Blockers ({blockers.length})
        </button>
        <button
          className={`flex-1 px-4 py-2 text-xs font-medium flex items-center justify-center gap-2 transition-colors ${
            activeTab === 'WARN'
              ? 'text-amber-400 border-b-2 border-amber-400 bg-amber-500/5'
              : 'text-slate-500 hover:text-slate-300'
          }`}
          onClick={() => setActiveTab('WARN')}
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          Warnings ({warnings.length})
        </button>
      </div>

      {/* Violations List */}
      <div className="flex-1 overflow-y-auto">
        {filteredViolations.length === 0 ? (
          <div className="p-4 text-center text-slate-500 text-sm">
            {activeTab === 'BLOCK' ? (
              <>
                <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p>No blockers</p>
                <p className="text-xs mt-1">Ready to publish!</p>
              </>
            ) : (
              <>
                <AlertTriangle className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p>No warnings</p>
              </>
            )}
          </div>
        ) : (
          <div className="divide-y divide-slate-800/50">
            {filteredViolations.map((violation) => (
              <ViolationItem
                key={violation.id}
                violation={violation}
                onClick={() => onViolationClick?.(violation)}
                onJump={() =>
                  violation.day && onJumpToCell?.(violation.driver_id, violation.day)
                }
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer Summary */}
      <div className="px-4 py-2 border-t border-slate-800 bg-slate-900/50 text-xs text-slate-500">
        {blockers.length === 0 ? (
          <span className="text-emerald-400">All blockers resolved</span>
        ) : (
          <span className="text-red-400">
            {blockers.length} blocker{blockers.length !== 1 ? 's' : ''} must be fixed
          </span>
        )}
      </div>
    </div>
  );
}

interface ViolationItemProps {
  violation: MatrixViolation;
  onClick?: () => void;
  onJump?: () => void;
}

function ViolationItem({ violation, onClick, onJump }: ViolationItemProps) {
  const isBlock = violation.severity === 'BLOCK';

  return (
    <div
      className={`p-3 hover:bg-slate-800/30 cursor-pointer transition-colors ${
        isBlock ? 'border-l-2 border-red-500' : 'border-l-2 border-amber-500'
      }`}
      onClick={onClick}
    >
      <div className="flex items-start gap-2">
        {isBlock ? (
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
        ) : (
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                isBlock
                  ? 'bg-red-500/20 text-red-400'
                  : 'bg-amber-500/20 text-amber-400'
              }`}
            >
              {violation.type}
            </span>
            <span className="text-xs text-slate-500 truncate">
              {violation.driver_id}
            </span>
          </div>
          <p className="text-sm text-slate-300 mt-1 line-clamp-2">{violation.message}</p>
          {violation.day && (
            <button
              className="flex items-center gap-1 mt-2 text-xs text-blue-400 hover:text-blue-300 transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                onJump?.();
              }}
            >
              <MapPin className="w-3 h-3" />
              Jump to {violation.day.toUpperCase()}
              <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
