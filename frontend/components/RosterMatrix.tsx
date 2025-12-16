// Roster Matrix Component
// Displays a matrix view with drivers as rows and weekdays as columns
// Cells show tour times formatted as HH:MM-HH:MM/HH:MM-HH:MM

import React from 'react';
import {
    ScheduleResponse,
    AssignmentOutput,
    Weekday
} from '../types';

interface RosterMatrixProps {
    schedule: ScheduleResponse;
}

// German day names (short) - Monday to Saturday only
const WEEKDAYS_DE: { key: Weekday; label: string }[] = [
    { key: 'MONDAY', label: 'Montag' },
    { key: 'TUESDAY', label: 'Dienstag' },
    { key: 'WEDNESDAY', label: 'Mittwoch' },
    { key: 'THURSDAY', label: 'Donnerstag' },
    { key: 'FRIDAY', label: 'Freitag' },
    { key: 'SATURDAY', label: 'Samstag' },
];

interface DriverRosterRow {
    driverId: string;
    driverName: string;
    dayAssignments: Map<string, AssignmentOutput>;
}

export default function RosterMatrix({ schedule }: RosterMatrixProps) {
    // Group assignments by driver
    const driverRows: DriverRosterRow[] = React.useMemo(() => {
        const driverMap = new Map<string, DriverRosterRow>();

        for (const assignment of schedule.assignments) {
            if (!driverMap.has(assignment.driver_id)) {
                driverMap.set(assignment.driver_id, {
                    driverId: assignment.driver_id,
                    driverName: assignment.driver_name,
                    dayAssignments: new Map(),
                });
            }

            const row = driverMap.get(assignment.driver_id)!;
            row.dayAssignments.set(assignment.day, assignment);
        }

        // Sort by driver name
        return Array.from(driverMap.values()).sort((a, b) =>
            a.driverName.localeCompare(b.driverName)
        );
    }, [schedule.assignments]);

    // Format tour times for a cell
    const formatTourTimes = (assignment: AssignmentOutput | undefined): string => {
        if (!assignment) return '-';

        const tours = assignment.block.tours;
        if (tours.length === 0) return '-';

        // Sort tours by start time
        const sortedTours = [...tours].sort((a, b) =>
            a.start_time.localeCompare(b.start_time)
        );

        // Format as "HH:MM-HH:MM"
        return sortedTours
            .map(tour => `${tour.start_time}-${tour.end_time}`)
            .join('/');
    };

    return (
        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
            <div className="bg-gradient-to-r from-emerald-600 to-teal-600 px-6 py-4">
                <h2 className="text-xl font-bold text-white">📋 Roster Matrix (Schichtplan)</h2>
                <p className="text-emerald-200 text-sm">
                    Wochenschichtplan für {driverRows.length} Fahrer
                </p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                    <thead>
                        <tr className="bg-gray-100 border-b-2 border-gray-300">
                            <th className="px-4 py-3 text-left text-sm font-bold text-gray-700 border-r border-gray-200 whitespace-nowrap">
                                Fahrer
                            </th>
                            {WEEKDAYS_DE.map(day => (
                                <th
                                    key={day.key}
                                    className="px-3 py-3 text-center text-sm font-bold text-gray-700 border-r border-gray-200 whitespace-nowrap min-w-[180px]"
                                >
                                    {day.label}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {driverRows.map((row, idx) => (
                            <tr
                                key={row.driverId}
                                className={`border-b border-gray-200 hover:bg-gray-50 transition-colors ${idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
                                    }`}
                            >
                                <td className="px-4 py-3 border-r border-gray-200">
                                    <div className="font-semibold text-gray-900">{row.driverName}</div>
                                    <div className="text-xs text-gray-500">{row.driverId}</div>
                                </td>
                                {WEEKDAYS_DE.map(day => {
                                    const assignment = row.dayAssignments.get(day.key);
                                    const tourText = formatTourTimes(assignment);
                                    const hasTours = tourText !== '-';

                                    return (
                                        <td
                                            key={day.key}
                                            className="px-2 py-2 text-center border-r border-gray-200"
                                        >
                                            <div className={`text-sm font-mono ${hasTours
                                                    ? 'text-gray-900 bg-emerald-50 border border-emerald-200 rounded-lg px-2 py-1'
                                                    : 'text-gray-400'
                                                }`}>
                                                {tourText}
                                            </div>
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {driverRows.length === 0 && (
                <div className="px-6 py-12 text-center text-gray-500">
                    Keine Fahrerzuweisungen vorhanden.
                </div>
            )}

            {/* Legend */}
            <div className="px-6 py-4 bg-gray-50 border-t border-gray-200">
                <div className="flex items-center gap-2 text-sm text-gray-600">
                    <span className="font-medium">Format:</span>
                    <code className="bg-emerald-50 border border-emerald-200 rounded px-2 py-0.5 font-mono text-xs">
                        Startzeit-Endzeit/Startzeit-Endzeit
                    </code>
                    <span className="text-gray-400 mx-2">|</span>
                    <span>Beispiel: 06:00-10:30/11:00-15:30/16:00-20:30</span>
                </div>
            </div>
        </div>
    );
}
