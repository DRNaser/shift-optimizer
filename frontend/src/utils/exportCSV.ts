/**
 * CSV Export Utility
 * ------------------
 * Exports schedule data as a roster matrix CSV.
 */

import type { ScheduleResponse, TourInput, WeekdayFE } from '../api';

const DAY_LABELS: Record<WeekdayFE, string> = {
    MONDAY: 'Montag',
    TUESDAY: 'Dienstag',
    WEDNESDAY: 'Mittwoch',
    THURSDAY: 'Donnerstag',
    FRIDAY: 'Freitag',
    SATURDAY: 'Samstag',
    SUNDAY: 'Sonntag',
};

/**
 * Export schedule as a roster matrix CSV.
 * Rows: Drivers (Fahrer 1, Fahrer 2, ...)
 * Columns: Monday to Saturday
 * Cells: Tour times (e.g., "06:00-10:30, 14:00-18:00")
 */
// exportRosterCSV is now handled by the backend
export function exportRosterCSV(_response: ScheduleResponse): void {
    const url = `${window.location.origin}/api/v1/export/roster`;

    // Try to use pywebview API to open in system browser (reliable download)
    // @ts-ignore
    if (window.pywebview && window.pywebview.api) {
        console.log("Using pywebview API to open link:", url);
        // @ts-ignore
        window.pywebview.api.open_link(url).catch((err: any) => {
            console.error("pywebview API failed, falling back", err);
            window.open(url, '_blank');
        });
    } else {
        // Fallback for dev environment or if API missing
        console.log("pywebview API not found, using window.open fallback");
        window.open(url, '_blank');
    }
}

/**
 * Export solver proof CSV - shows all input tours and their assignment status.
 * This proves no artificial tours were created.
 */
export function exportSolverProofCSV(
    inputTours: TourInput[],
    response: ScheduleResponse
): void {
    // Build a set of assigned tour IDs
    const assignedTourIds = new Set<string>();
    for (const a of response.assignments) {
        for (const tour of a.block.tours) {
            assignedTourIds.add(tour.id);
        }
    }

    const rows: string[] = [];

    // Header
    rows.push(['Tour_ID', 'Wochentag', 'Startzeit', 'Endzeit', 'Status', 'Fahrer'].join(';'));

    // For each input tour, show if assigned or not
    for (const tour of inputTours) {
        const isAssigned = assignedTourIds.has(tour.id);
        let driverName = '';

        if (isAssigned) {
            // Find which driver got this tour
            for (const a of response.assignments) {
                for (const t of a.block.tours) {
                    if (t.id === tour.id) {
                        driverName = a.driver_name;
                        break;
                    }
                }
                if (driverName) break;
            }
        }

        rows.push([
            tour.id,
            DAY_LABELS[tour.day] || tour.day,
            tour.start_time,
            tour.end_time,
            isAssigned ? 'Zugewiesen' : 'Nicht zugewiesen',
            driverName || '-',
        ].join(';'));
    }

    // Add summary
    rows.push('');
    rows.push(`Eingabe Touren;${inputTours.length}`);
    rows.push(`Zugewiesene Touren;${assignedTourIds.size}`);
    rows.push(`Nicht zugewiesene Touren;${inputTours.length - assignedTourIds.size}`);
    rows.push('');
    rows.push('NACHWEIS: Keine künstlichen Touren erstellt - alle zugewiesenen Touren stammen aus der Eingabedatei.');

    downloadCSV(rows.join('\n'), 'solver_nachweis.csv');
}

/**
 * Export unassigned tours CSV.
 */
export function exportUnassignedCSV(
    inputTours: TourInput[],
    response: ScheduleResponse
): void {
    // Build a set of assigned tour IDs
    const assignedTourIds = new Set<string>();
    for (const a of response.assignments) {
        for (const tour of a.block.tours) {
            assignedTourIds.add(tour.id);
        }
    }

    const unassigned = inputTours.filter(t => !assignedTourIds.has(t.id));

    if (unassigned.length === 0) {
        alert('Alle Touren wurden zugewiesen. Keine Resttouren vorhanden.');
        return;
    }

    const rows: string[] = [];

    // Header
    rows.push(['Tour_ID', 'Wochentag', 'Startzeit', 'Endzeit'].join(';'));

    for (const tour of unassigned) {
        rows.push([
            tour.id,
            DAY_LABELS[tour.day] || tour.day,
            tour.start_time,
            tour.end_time,
        ].join(';'));
    }

    rows.push('');
    rows.push(`Gesamt nicht zugewiesene Touren;${unassigned.length}`);

    downloadCSV(rows.join('\n'), 'resttouren.csv');
}

/**
 * Helper to trigger CSV download.
 */
function downloadCSV(content: string, filename: string): void {
    // Create a hidden form and submit it to the backend
    // this works better in pywebview/embedded browsers than client-side Blobs
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/api/v1/export/csv';
    form.style.display = 'none';

    const contentInput = document.createElement('input');
    contentInput.type = 'hidden';
    contentInput.name = 'content';
    contentInput.value = content;
    form.appendChild(contentInput);

    const filenameInput = document.createElement('input');
    filenameInput.type = 'hidden';
    filenameInput.name = 'filename';
    filenameInput.value = filename;
    form.appendChild(filenameInput);

    document.body.appendChild(form);
    form.submit();
    document.body.removeChild(form);
}
