'use client';

import { useMemo, useState, useCallback } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
  type ColumnDef,
} from '@tanstack/react-table';
import { Pin, AlertCircle, AlertTriangle, CheckCircle } from 'lucide-react';
import { ShiftCell, type CellData } from './shift-cell';

export interface MatrixDriver {
  driver_id: string;
  driver_name: string;
  external_id?: string;
  total_hours: number;
  block_count: number;
  warn_count: number;
}

export interface MatrixCell {
  driver_id: string;
  day: string; // 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
  tour_instance_id: number | null;
  tour_name: string | null;
  block_type: string | null;
  start_time: string | null;
  end_time: string | null;
  hours: number | null;
  is_pinned: boolean;
  pin_id: number | null;
  severity: 'BLOCK' | 'WARN' | 'OK' | null;
  violations: string[];
}

export interface MatrixViolation {
  id: string;
  type: string;
  severity: 'BLOCK' | 'WARN';
  driver_id: string;
  day: string | null;
  message: string;
  details?: Record<string, unknown>;
}

export interface MatrixData {
  drivers: MatrixDriver[];
  days: string[];
  cells: MatrixCell[];
  violations: MatrixViolation[];
}

interface MatrixGridProps {
  data: MatrixData;
  onCellClick?: (cell: CellData) => void;
  onPinToggle?: (driverId: string, day: string, tourInstanceId: number | null) => void;
  selectedCell?: { driverId: string; day: string } | null;
}

interface DriverRow {
  driver_id: string;
  driver_name: string;
  total_hours: number;
  block_count: number;
  warn_count: number;
  cells: Record<string, MatrixCell>;
}

const columnHelper = createColumnHelper<DriverRow>();

const DAY_LABELS: Record<string, string> = {
  mon: 'Mon',
  tue: 'Tue',
  wed: 'Wed',
  thu: 'Thu',
  fri: 'Fri',
  sat: 'Sat',
  sun: 'Sun',
};

export function MatrixGrid({
  data,
  onCellClick,
  onPinToggle,
  selectedCell,
}: MatrixGridProps) {
  // Transform flat cells into rows with day columns
  const rows = useMemo<DriverRow[]>(() => {
    const cellMap = new Map<string, MatrixCell>();
    data.cells.forEach((cell) => {
      const key = `${cell.driver_id}:${cell.day}`;
      cellMap.set(key, cell);
    });

    return data.drivers.map((driver) => {
      const cells: Record<string, MatrixCell> = {};
      data.days.forEach((day) => {
        const cell = cellMap.get(`${driver.driver_id}:${day}`);
        if (cell) {
          cells[day] = cell;
        } else {
          // Empty cell
          cells[day] = {
            driver_id: driver.driver_id,
            day,
            tour_instance_id: null,
            tour_name: null,
            block_type: null,
            start_time: null,
            end_time: null,
            hours: null,
            is_pinned: false,
            pin_id: null,
            severity: null,
            violations: [],
          };
        }
      });

      return {
        driver_id: driver.driver_id,
        driver_name: driver.driver_name,
        total_hours: driver.total_hours,
        block_count: driver.block_count,
        warn_count: driver.warn_count,
        cells,
      };
    });
  }, [data]);

  const handleCellClick = useCallback(
    (row: DriverRow, day: string) => {
      const cell = row.cells[day];
      if (onCellClick && cell) {
        onCellClick({
          driverId: row.driver_id,
          driverName: row.driver_name,
          day,
          cell,
        });
      }
    },
    [onCellClick]
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const columns = useMemo(() => {
    const cols: ColumnDef<DriverRow, any>[] = [
      // Driver column
      columnHelper.accessor('driver_name', {
        header: () => <span className="text-xs uppercase tracking-wider">Driver</span>,
        cell: (info) => {
          const row = info.row.original;
          return (
            <div className="flex flex-col">
              <span className="font-medium text-slate-200 text-sm">{row.driver_name}</span>
              <span className="text-xs text-slate-500 font-mono">{row.driver_id}</span>
            </div>
          );
        },
        size: 150,
      }),
    ];

    // Day columns
    data.days.forEach((day) => {
      cols.push({
        id: day,
        header: () => (
          <span className="text-xs uppercase tracking-wider">{DAY_LABELS[day] || day}</span>
        ),
        cell: (info) => {
          const row = info.row.original;
          const cell = row.cells[day];
          const isSelected =
            selectedCell?.driverId === row.driver_id && selectedCell?.day === day;

          return (
            <ShiftCell
              cell={cell}
              isSelected={isSelected}
              onClick={() => handleCellClick(row, day)}
              onPinToggle={
                onPinToggle
                  ? () => onPinToggle(row.driver_id, day, cell.tour_instance_id)
                  : undefined
              }
            />
          );
        },
        size: 100,
      });
    });

    // Summary columns
    cols.push(
      columnHelper.accessor('total_hours', {
        header: () => <span className="text-xs uppercase tracking-wider">Hours</span>,
        cell: (info) => (
          <span className="font-mono text-emerald-400 font-medium text-sm">
            {info.getValue().toFixed(1)}h
          </span>
        ),
        size: 70,
      }),
      {
        id: 'status',
        header: () => <span className="text-xs uppercase tracking-wider">Status</span>,
        cell: (info) => {
          const row = info.row.original;
          if (row.block_count > 0) {
            return (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                <AlertCircle className="w-3 h-3" />
                {row.block_count}
              </span>
            );
          }
          if (row.warn_count > 0) {
            return (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
                <AlertTriangle className="w-3 h-3" />
                {row.warn_count}
              </span>
            );
          }
          return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              <CheckCircle className="w-3 h-3" />
              OK
            </span>
          );
        },
        size: 80,
      }
    );

    return cols;
  }, [data.days, handleCellClick, onPinToggle, selectedCell]);

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (data.drivers.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-8 text-center">
        <p className="text-slate-500">No roster data available.</p>
        <p className="text-slate-600 text-sm mt-1">
          Run the solver to generate assignments.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-slate-800">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className="px-3 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider bg-slate-900/80 sticky top-0"
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row, i) => (
              <tr
                key={row.id}
                className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                  i % 2 === 0 ? 'bg-slate-900/30' : ''
                }`}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2 border-t border-slate-800 bg-slate-900/50 text-xs text-slate-500 flex items-center justify-between">
        <span>{data.drivers.length} drivers</span>
        <span>
          {data.violations.filter((v) => v.severity === 'BLOCK').length} blockers,{' '}
          {data.violations.filter((v) => v.severity === 'WARN').length} warnings
        </span>
      </div>
    </div>
  );
}
