// Excel Export Component
// Generates and downloads Excel file with schedule data

import * as XLSX from 'xlsx';
import { ScheduleResponse } from '../types';

interface ExportButtonProps {
    schedule: ScheduleResponse | null;
    disabled?: boolean;
}

export default function ExportButton({ schedule, disabled = false }: ExportButtonProps) {
    const handleExport = () => {
        if (!schedule) return;

        // Create workbook
        const wb = XLSX.utils.book_new();

        // Sheet 1: Schedule Overview
        const scheduleData = [];
        scheduleData.push(['Driver', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'Total Hours']);

        // Group by driver
        const driverMap = new Map<string, any>();
        schedule.assignments.forEach(assignment => {
            if (!driverMap.has(assignment.driver_id)) {
                driverMap.set(assignment.driver_id, {
                    name: assignment.driver_name,
                    Monday: '',
                    Tuesday: '',
                    Wednesday: '',
                    Thursday: '',
                    Friday: '',
                    Saturday: '',
                    Sunday: '',
                    totalHours: 0,
                });
            }
            const driver = driverMap.get(assignment.driver_id)!;
            driver[assignment.day] = `${assignment.block.tours.length}× (${assignment.block.total_work_hours.toFixed(1)}h)`;
            driver.totalHours += assignment.block.total_work_hours;
        });

        driverMap.forEach((driver) => {
            scheduleData.push([
                driver.name,
                driver.Monday,
                driver.Tuesday,
                driver.Wednesday,
                driver.Thursday,
                driver.Friday,
                driver.Saturday,
                driver.Sunday,
                `${driver.totalHours.toFixed(1)}h`,
            ]);
        });

        const ws1 = XLSX.utils.aoa_to_sheet(scheduleData);
        XLSX.utils.book_append_sheet(wb, ws1, 'Schedule');

        // Sheet 2: Assignments Detail
        const assignmentsData = [];
        assignmentsData.push(['Driver', 'Day', 'Block Type', 'Tours', 'Total Hours', 'Span Hours', 'Tour IDs']);

        schedule.assignments.forEach(assignment => {
            const tourIds = assignment.block.tours.map(t => t.id).join(', ');
            assignmentsData.push([
                assignment.driver_name,
                assignment.day,
                assignment.block.block_type.toUpperCase(),
                assignment.block.tours.length,
                assignment.block.total_work_hours.toFixed(1),
                assignment.block.span_hours.toFixed(1),
                tourIds,
            ]);
        });

        const ws2 = XLSX.utils.aoa_to_sheet(assignmentsData);
        XLSX.utils.book_append_sheet(wb, ws2, 'Assignments');

        // Sheet 3: Unassigned Tours
        if (schedule.unassigned_tours.length > 0) {
            const unassignedData = [];
            unassignedData.push(['Tour ID', 'Day', 'Start Time', 'End Time', 'Duration', 'Reason']);

            schedule.unassigned_tours.forEach(unassigned => {
                unassignedData.push([
                    unassigned.tour.id,
                    unassigned.tour.day,
                    unassigned.tour.start_time,
                    unassigned.tour.end_time,
                    `${unassigned.tour.duration_hours.toFixed(1)}h`,
                    unassigned.details,
                ]);
            });

            const ws3 = XLSX.utils.aoa_to_sheet(unassignedData);
            XLSX.utils.book_append_sheet(wb, ws3, 'Unassigned');
        }

        // Sheet 4: Statistics
        const statsData = [];
        statsData.push(['Metric', 'Value']);
        statsData.push(['Week Start', schedule.week_start]);
        statsData.push(['Solver Type', schedule.solver_type.toUpperCase()]);
        statsData.push(['Total Drivers', schedule.stats.total_drivers]);
        statsData.push(['Total Tours (Input)', schedule.stats.total_tours_input]);
        statsData.push(['Tours Assigned', schedule.stats.total_tours_assigned]);
        statsData.push(['Tours Unassigned', schedule.stats.total_tours_unassigned]);
        statsData.push(['Assignment Rate', `${(schedule.stats.assignment_rate * 100).toFixed(1)}%`]);
        statsData.push(['Avg Driver Utilization', `${(schedule.stats.average_driver_utilization * 100).toFixed(1)}%`]);
        statsData.push(['']);
        statsData.push(['Block Distribution', '']);
        statsData.push(['3er Blocks', schedule.stats.block_counts['triple'] || 0]);
        statsData.push(['2er Blocks', schedule.stats.block_counts['double'] || 0]);
        statsData.push(['1er Blocks', schedule.stats.block_counts['single'] || 0]);
        statsData.push(['']);
        statsData.push(['Validation', schedule.validation.is_valid ? 'Valid ✓' : 'Invalid ✗']);
        if (schedule.validation.hard_violations.length > 0) {
            statsData.push(['Violations', schedule.validation.hard_violations.join(', ')]);
        }

        const ws4 = XLSX.utils.aoa_to_sheet(statsData);
        XLSX.utils.book_append_sheet(wb, ws4, 'Statistics');

        // Sheet 5: Roster Matrix (Schichtplan)
        const rosterData: any[][] = [];

        // German day names (Mon-Sat only, as per user request)
        const weekdayDE = [
            { key: 'MONDAY', label: 'Montag' },
            { key: 'TUESDAY', label: 'Dienstag' },
            { key: 'WEDNESDAY', label: 'Mittwoch' },
            { key: 'THURSDAY', label: 'Donnerstag' },
            { key: 'FRIDAY', label: 'Freitag' },
            { key: 'SATURDAY', label: 'Samstag' },
        ];

        // Header row
        rosterData.push(['Fahrer', ...weekdayDE.map(d => d.label)]);

        // Build driver -> day -> tour times map
        // First, accumulate tours (as objects) then format to strings
        type TourTime = { start: string; end: string };
        const tourAccumulator = new Map<string, { name: string; days: Map<string, TourTime[]> }>();

        schedule.assignments.forEach(assignment => {
            if (!tourAccumulator.has(assignment.driver_id)) {
                tourAccumulator.set(assignment.driver_id, {
                    name: assignment.driver_name,
                    days: new Map(),
                });
            }

            const driver = tourAccumulator.get(assignment.driver_id)!;

            // Get all tours from this block
            const newTours: TourTime[] = assignment.block.tours.map(tour => ({
                start: tour.start_time,
                end: tour.end_time,
            }));

            // Accumulate tours for this day (a driver might have multiple blocks per day)
            const existingTours = driver.days.get(assignment.day) || [];
            const allTours = [...existingTours, ...newTours];

            driver.days.set(assignment.day, allTours);
        });

        // Now format the accumulated tours for each driver/day
        const rosterMap = new Map<string, { name: string; days: Map<string, string> }>();
        tourAccumulator.forEach((driver, driverId) => {
            const formattedDays = new Map<string, string>();
            driver.days.forEach((tours, day) => {
                // Sort tours by start time and format as HH:MM-HH:MM/HH:MM-HH:MM
                const formattedTours = tours
                    .sort((a, b) => a.start.localeCompare(b.start))
                    .map(t => `${t.start}-${t.end}`)
                    .join('/');
                formattedDays.set(day, formattedTours);
            });
            rosterMap.set(driverId, { name: driver.name, days: formattedDays });
        });

        // Add driver rows sorted by name
        const sortedDrivers = Array.from(rosterMap.entries()).sort((a, b) =>
            a[1].name.localeCompare(b[1].name)
        );

        for (const [_driverId, driver] of sortedDrivers) {
            const row = [driver.name];
            for (const dayInfo of weekdayDE) {
                row.push(driver.days.get(dayInfo.key) || '-');
            }
            rosterData.push(row);
        }

        const ws5 = XLSX.utils.aoa_to_sheet(rosterData);

        // Set column widths for better readability
        ws5['!cols'] = [
            { wch: 20 },  // Fahrer column
            { wch: 30 },  // Montag
            { wch: 30 },  // Dienstag
            { wch: 30 },  // Mittwoch
            { wch: 30 },  // Donnerstag
            { wch: 30 },  // Freitag
            { wch: 30 },  // Samstag
        ];

        XLSX.utils.book_append_sheet(wb, ws5, 'Schichtplan');

        // Generate file
        const fileName = `shift-schedule-${schedule.week_start}-${schedule.solver_type}.xlsx`;
        XLSX.writeFile(wb, fileName);
    };

    return (
        <button
            onClick={handleExport}
            disabled={disabled || !schedule}
            className="export-btn"
            title="Export schedule to Excel"
        >
            <span className="export-icon">📊</span>
            <span>Export to Excel</span>

            <style>{`
        .export-btn {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 10px 20px;
          background: linear-gradient(135deg, #22c55e, #16a34a);
          color: white;
          border: none;
          border-radius: 8px;
          font-weight: 600;
          font-size: 14px;
          cursor: pointer;
          transition: all 250ms;
          box-shadow: 0 2px 8px rgba(34, 197, 94, 0.2);
        }

        .export-btn:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(34, 197, 94, 0.3);
        }

        .export-btn:active:not(:disabled) {
          transform: translateY(0);
        }

        .export-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .export-icon {
          font-size: 18px;
        }
      `}</style>
        </button>
    );
}
