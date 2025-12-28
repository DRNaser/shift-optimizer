import { RosterRow, RunInsights } from "./types";

/**
 * SOLVEREIGN CSV Export Utilities
 * - UTF-8 BOM for Excel compatibility
 * - Semicolon separator (German locale)
 * - CRLF line endings
 */

const BOM = "\uFEFF";
const SEPARATOR = ";";
const LINE_END = "\r\n";

function escapeCSV(value: string): string {
    if (value.includes(SEPARATOR) || value.includes('"') || value.includes("\n")) {
        return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
}

function triggerDownload(content: string, filename: string, mimeType: string) {
    const blob = new Blob([content], { type: mimeType });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

/**
 * Export Roster Matrix to CSV
 * Columns: Driver ID, Name, Type, Weekly Hours, Mon, Tue, Wed, Thu, Fri, Sat
 */
export function exportRosterToCSV(roster: RosterRow[], runId: string) {
    const days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];
    const header = ["Fahrer-ID", "Name", "Typ", "Wochenstunden", ...days].join(SEPARATOR);

    const rows = roster.map(row => {
        const shiftCells = row.shifts.map(shift => {
            if (!shift) return "frei";
            const type = shift.type === '2er_split' ? 'Split' : shift.type;
            return escapeCSV(`${shift.start_time}-${shift.end_time} (${type})`);
        });

        return [
            escapeCSV(row.driver_id),
            escapeCSV(row.driver_name),
            row.driver_type === 'FTE' ? 'Vollzeit' : row.driver_type === 'PT_core' ? 'Teilzeit-Core' : 'Teilzeit-Flex',
            row.weekly_hours.toFixed(2).replace('.', ','), // German decimal
            ...shiftCells
        ].join(SEPARATOR);
    });

    const csvContent = BOM + [header, ...rows].join(LINE_END);
    triggerDownload(csvContent, `solvereign_${runId}_roster.csv`, 'text/csv;charset=utf-8');
}

/**
 * Export Insights/KPIs to CSV
 */
export function exportInsightsToCSV(insights: RunInsights, runId: string) {
    const header = ["Kennzahl", "Wert"].join(SEPARATOR);

    // Human-readable metric names
    const metricNames: Record<string, string> = {
        total_hours: "Gesamtstunden",
        core_share: "Core PT Anteil (%)",
        orphans_count: "Nicht zugewiesene Touren",
        violation_count: "Verstöße",
        drivers_total: "Fahrer Gesamt",
        drivers_fte: "FTE Fahrer",
        drivers_pt: "PT Fahrer",
        assignment_rate: "Zuweisungsrate (%)",
        avg_utilization: "Durchschn. Auslastung (%)",
    };

    const rows = Object.entries(insights).map(([key, value]) => {
        const label = metricNames[key] || key;
        const formattedValue = typeof value === 'number'
            ? value.toFixed(2).replace('.', ',')
            : String(value);
        return [escapeCSV(label), formattedValue].join(SEPARATOR);
    });

    const csvContent = BOM + [header, ...rows].join(LINE_END);
    triggerDownload(csvContent, `solvereign_${runId}_insights.csv`, 'text/csv;charset=utf-8');
}

/**
 * Export complete run package (Roster + Insights)
 */
export function exportRunPackage(data: { roster: RosterRow[], insights: RunInsights, id: string }) {
    exportRosterToCSV(data.roster, data.id);
    // Small timeout to allow browser to handle second download
    setTimeout(() => exportInsightsToCSV(data.insights, data.id), 500);
}
