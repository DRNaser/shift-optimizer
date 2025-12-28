"use client";

import {
    useReactTable,
    getCoreRowModel,
    flexRender,
    createColumnHelper,
    type ColumnDef,
} from "@tanstack/react-table";
import { useMemo } from "react";

interface DriverRow {
    driverId: string;
    driverName: string;
    monday: string;
    tuesday: string;
    wednesday: string;
    thursday: string;
    friday: string;
    saturday: string;
    totalHours: number;
}

interface MatrixViewProps {
    data: DriverRow[];
}

const columnHelper = createColumnHelper<DriverRow>();

export function MatrixView({ data }: MatrixViewProps) {
    const columns = useMemo<ColumnDef<DriverRow, any>[]>(
        () => [
            columnHelper.accessor("driverId", {
                header: "ID",
                cell: (info) => (
                    <span className="font-mono text-blue-400">{info.getValue()}</span>
                ),
            }),
            columnHelper.accessor("monday", {
                header: "Mon",
                cell: (info) => <CellContent value={info.getValue()} />,
            }),
            columnHelper.accessor("tuesday", {
                header: "Tue",
                cell: (info) => <CellContent value={info.getValue()} />,
            }),
            columnHelper.accessor("wednesday", {
                header: "Wed",
                cell: (info) => <CellContent value={info.getValue()} />,
            }),
            columnHelper.accessor("thursday", {
                header: "Thu",
                cell: (info) => <CellContent value={info.getValue()} />,
            }),
            columnHelper.accessor("friday", {
                header: "Fri",
                cell: (info) => <CellContent value={info.getValue()} />,
            }),
            columnHelper.accessor("saturday", {
                header: "Sat",
                cell: (info) => <CellContent value={info.getValue()} />,
            }),
            columnHelper.accessor("totalHours", {
                header: "Hours",
                cell: (info) => (
                    <span className="font-mono text-emerald-400 font-medium">
                        {info.getValue().toFixed(1)}h
                    </span>
                ),
            }),
        ],
        []
    );

    const table = useReactTable({
        data,
        columns,
        getCoreRowModel: getCoreRowModel(),
    });

    if (data.length === 0) {
        return (
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-8 text-center">
                <p className="text-slate-500">No roster data available.</p>
                <p className="text-slate-600 text-sm mt-1">
                    Upload a CSV file to generate the schedule.
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
                                        className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider bg-slate-900/50"
                                    >
                                        {flexRender(
                                            header.column.columnDef.header,
                                            header.getContext()
                                        )}
                                    </th>
                                ))}
                            </tr>
                        ))}
                    </thead>
                    <tbody>
                        {table.getRowModel().rows.map((row, i) => (
                            <tr
                                key={row.id}
                                className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${i % 2 === 0 ? "bg-slate-900/30" : ""
                                    }`}
                            >
                                {row.getVisibleCells().map((cell) => (
                                    <td key={cell.id} className="px-4 py-2 text-slate-300">
                                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="px-4 py-2 border-t border-slate-800 bg-slate-900/50 text-xs text-slate-500">
                {data.length} drivers
            </div>
        </div>
    );
}

function CellContent({ value }: { value: string }) {
    if (!value) return <span className="text-slate-700">—</span>;

    // Parse block type for coloring (matching shift-pill.tsx)
    const isTriple = value.includes("[triple]") || value.includes("[3er]");
    const isSplit = value.includes("[split]") || value.includes("[2er_split]");
    const isDouble = value.includes("[double]") || value.includes("[2er]");
    const isSingle = value.includes("[single]") || value.includes("[1er]");

    // Color scheme: 3er=Orange, 2er=Blue, 2er_split=Grey, 1er=Green
    let color = "text-slate-400";
    if (isTriple) color = "text-orange-400";
    else if (isSplit) color = "text-slate-400";
    else if (isDouble) color = "text-blue-400";
    else if (isSingle) color = "text-emerald-400";

    return (
        <span className={`font-mono text-xs font-medium ${color}`} title={value}>
            {value.substring(0, 20)}
            {value.length > 20 ? "..." : ""}
        </span>
    );
}

export type { DriverRow };
