'use client';

import { Pin, AlertCircle, AlertTriangle, Minus } from 'lucide-react';
import type { MatrixCell } from './matrix-grid';

export interface CellData {
  driverId: string;
  driverName: string;
  day: string;
  cell: MatrixCell;
}

interface ShiftCellProps {
  cell: MatrixCell;
  isSelected?: boolean;
  onClick?: () => void;
  onPinToggle?: () => void;
}

// Block type colors matching existing shift-pill.tsx
const BLOCK_TYPE_COLORS: Record<string, string> = {
  '3er': 'bg-orange-500/20 text-orange-400 border-orange-500/40',
  triple: 'bg-orange-500/20 text-orange-400 border-orange-500/40',
  '2er': 'bg-blue-500/20 text-blue-400 border-blue-500/40',
  double: 'bg-blue-500/20 text-blue-400 border-blue-500/40',
  '2er_split': 'bg-slate-500/20 text-slate-400 border-slate-500/40',
  split: 'bg-slate-500/20 text-slate-400 border-slate-500/40',
  '1er': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40',
  single: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40',
};

function getBlockTypeColor(blockType: string | null): string {
  if (!blockType) return 'bg-slate-700/30 text-slate-500 border-slate-700/50';
  const normalized = blockType.toLowerCase().replace(/[[\]]/g, '');
  return BLOCK_TYPE_COLORS[normalized] || 'bg-slate-700/30 text-slate-500 border-slate-700/50';
}

function getSeverityIndicator(severity: 'BLOCK' | 'WARN' | 'OK' | null) {
  if (severity === 'BLOCK') {
    return <AlertCircle className="w-3 h-3 text-red-400 absolute -top-1 -right-1" />;
  }
  if (severity === 'WARN') {
    return <AlertTriangle className="w-3 h-3 text-amber-400 absolute -top-1 -right-1" />;
  }
  return null;
}

export function ShiftCell({ cell, isSelected, onClick, onPinToggle }: ShiftCellProps) {
  const isEmpty = !cell.tour_name && !cell.block_type;
  const isUnassigned = cell.severity === 'BLOCK' && isEmpty;

  if (isEmpty && !isUnassigned) {
    return (
      <div
        className={`
          relative min-h-[40px] min-w-[70px] rounded-md border-2 border-dashed
          flex items-center justify-center cursor-pointer transition-all
          ${isSelected ? 'border-blue-500 bg-blue-500/10' : 'border-slate-700/50 hover:border-slate-600'}
        `}
        onClick={onClick}
      >
        <Minus className="w-4 h-4 text-slate-600" />
      </div>
    );
  }

  const colorClass = getBlockTypeColor(cell.block_type);
  const label = cell.tour_name || cell.block_type || 'UNASSIGNED';
  const timeLabel = cell.start_time && cell.end_time
    ? `${cell.start_time.slice(0, 5)}-${cell.end_time.slice(0, 5)}`
    : null;

  return (
    <div
      className={`
        relative min-h-[40px] min-w-[70px] p-1.5 rounded-md border
        flex flex-col items-center justify-center cursor-pointer transition-all
        ${colorClass}
        ${isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-900' : 'hover:opacity-90'}
        ${isUnassigned ? 'bg-red-500/20 text-red-400 border-red-500/40' : ''}
      `}
      onClick={onClick}
      title={cell.violations.join('\n') || label}
    >
      {/* Severity indicator */}
      {getSeverityIndicator(cell.severity)}

      {/* Pin indicator */}
      {cell.is_pinned && (
        <Pin
          className="w-3 h-3 text-purple-400 absolute -top-1 -left-1 cursor-pointer"
          onClick={(e) => {
            e.stopPropagation();
            onPinToggle?.();
          }}
        />
      )}

      {/* Content */}
      <span className="font-mono text-xs font-medium truncate max-w-full">
        {label.length > 8 ? `${label.slice(0, 8)}..` : label}
      </span>
      {timeLabel && (
        <span className="text-[10px] opacity-70 truncate">{timeLabel}</span>
      )}
      {cell.hours && (
        <span className="text-[10px] opacity-60">{cell.hours.toFixed(1)}h</span>
      )}
    </div>
  );
}
