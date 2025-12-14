// Week Overview Grid Component
// Displays the weekly schedule as a visual grid

import React, { useState } from 'react';
import {
    ScheduleResponse,
    AssignmentOutput,
    WEEKDAYS,
    DAY_SHORT,
    getBlockTypeColor,
    BlockType
} from '../types';
import BlockDetailModal from './BlockDetailModal';

interface WeekOverviewProps {
    schedule: ScheduleResponse;
    onBlockClick?: (assignment: AssignmentOutput) => void;
}

interface DriverRow {
    driverId: string;
    driverName: string;
    dayBlocks: Map<string, AssignmentOutput>;
    totalHours: number;
}

export default function WeekOverview({ schedule, onBlockClick }: WeekOverviewProps) {
    const [selectedAssignment, setSelectedAssignment] = useState<AssignmentOutput | null>(null);

    // Group assignments by driver
    const driverRows: DriverRow[] = React.useMemo(() => {
        const driverMap = new Map<string, DriverRow>();

        for (const assignment of schedule.assignments) {
            if (!driverMap.has(assignment.driver_id)) {
                driverMap.set(assignment.driver_id, {
                    driverId: assignment.driver_id,
                    driverName: assignment.driver_name,
                    dayBlocks: new Map(),
                    totalHours: 0,
                });
            }

            const row = driverMap.get(assignment.driver_id)!;
            row.dayBlocks.set(assignment.day, assignment);
            row.totalHours += assignment.block.total_work_hours;
        }

        return Array.from(driverMap.values());
    }, [schedule.assignments]);

    return (
        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
            <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-6 py-4">
                <h2 className="text-xl font-bold text-white">Week Overview</h2>
                <p className="text-indigo-200 text-sm">
                    {schedule.stats.total_tours_assigned} tours assigned to {schedule.stats.total_drivers} drivers
                </p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead>
                        <tr className="bg-gray-50 border-b border-gray-200">
                            <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600 w-40">
                                Driver
                            </th>
                            {WEEKDAYS.map(day => (
                                <th key={day} className="px-2 py-3 text-center text-sm font-semibold text-gray-600 w-28">
                                    {DAY_SHORT[day]}
                                </th>
                            ))}
                            <th className="px-4 py-3 text-right text-sm font-semibold text-gray-600 w-20">
                                Hours
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {driverRows.map((row, idx) => (
                            <tr
                                key={row.driverId}
                                className={`border-b border-gray-100 hover:bg-gray-50 transition-colors ${idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
                                    }`}
                            >
                                <td className="px-4 py-3">
                                    <div className="font-medium text-gray-900">{row.driverName}</div>
                                    <div className="text-xs text-gray-500">{row.driverId}</div>
                                </td>
                                {WEEKDAYS.map(day => {
                                    const assignment = row.dayBlocks.get(day);
                                    return (
                                        <td key={day} className="px-2 py-2">
                                            {assignment ? (
                                                <BlockCell
                                                    assignment={assignment}
                                                    onClick={() => {
                                                        setSelectedAssignment(assignment);
                                                        onBlockClick?.(assignment);
                                                    }}
                                                />
                                            ) : (
                                                <div className="h-12 rounded border-2 border-dashed border-gray-200" />
                                            )}
                                        </td>
                                    );
                                })}
                                <td className="px-4 py-3 text-right">
                                    <span className={`font-semibold ${row.totalHours > 50 ? 'text-amber-600' : 'text-gray-700'
                                        }`}>
                                        {row.totalHours.toFixed(1)}h
                                    </span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {driverRows.length === 0 && (
                <div className="px-6 py-12 text-center text-gray-500">
                    No assignments yet. Run the optimizer to see results.
                </div>
            )}

            {/* Legend */}
            <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex flex-wrap gap-4">
                <LegendItem color={getBlockTypeColor('triple')} label="3er (3 tours)" />
                <LegendItem color={getBlockTypeColor('double')} label="2er (2 tours)" />
                <LegendItem color={getBlockTypeColor('single')} label="1er (1 tour)" />
            </div>

            {/* Block Detail Modal */}
            <BlockDetailModal
                assignment={selectedAssignment}
                isOpen={selectedAssignment !== null}
                onClose={() => setSelectedAssignment(null)}
            />
        </div>
    );
}

// Block cell component
interface BlockCellProps {
    assignment: AssignmentOutput;
    onClick?: () => void;
}

function BlockCell({ assignment, onClick }: BlockCellProps) {
    const { block } = assignment;
    const color = getBlockTypeColor(block.block_type as BlockType);

    return (
        <button
            onClick={onClick}
            className="w-full h-12 rounded-lg flex flex-col items-center justify-center text-white font-medium shadow-sm hover:shadow-md transition-all cursor-pointer transform hover:scale-105"
            style={{ backgroundColor: color }}
        >
            <span className="text-sm font-bold">
                {block.tours.length}x
            </span>
            <span className="text-xs opacity-90">
                {block.total_work_hours.toFixed(1)}h
            </span>
        </button>
    );
}

// Legend item
interface LegendItemProps {
    color: string;
    label: string;
}

function LegendItem({ color, label }: LegendItemProps) {
    return (
        <div className="flex items-center gap-2">
            <div
                className="w-4 h-4 rounded"
                style={{ backgroundColor: color }}
            />
            <span className="text-sm text-gray-600">{label}</span>
        </div>
    );
}
