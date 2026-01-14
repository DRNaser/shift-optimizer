import type { AssignmentOutput } from "./api";
import type { DriverRow } from "@/components/ui/matrix-view";

// =============================================================================
// DATA QUALITY TRACKING
// =============================================================================

export interface MissingBlockInfo {
    driver_id: string;
    driver_name: string;
    day: string;
}

export interface DataQualityReport {
    total_assignments: number;
    valid_assignments: number;
    missing_block_count: number;
    missing_block_ids: MissingBlockInfo[]; // First 10 for display
    has_data_loss: boolean;
}

/**
 * Analyze assignments for data quality issues
 * Returns a report of missing blocks - NEVER silently drops data
 */
export function analyzeAssignments(assignments: AssignmentOutput[]): DataQualityReport {
    const missingBlocks: MissingBlockInfo[] = [];

    assignments.forEach((a) => {
        if (!a.block) {
            missingBlocks.push({
                driver_id: a.driver_id,
                driver_name: a.driver_name,
                day: a.day,
            });
        }
    });

    // Log to console for server-side visibility (will appear in browser console)
    if (missingBlocks.length > 0) {
        console.error(`[DATA QUALITY] Missing blocks detected: ${missingBlocks.length}/${assignments.length} assignments`);
        console.error(`[DATA QUALITY] First 10 missing:`, missingBlocks.slice(0, 10));
    }

    return {
        total_assignments: assignments.length,
        valid_assignments: assignments.length - missingBlocks.length,
        missing_block_count: missingBlocks.length,
        missing_block_ids: missingBlocks.slice(0, 10), // First 10 for display
        has_data_loss: missingBlocks.length > 0,
    };
}

// =============================================================================
// CSV EXPORT
// =============================================================================

/**
 * Master Export - V5 Contract
 * UTF-8 BOM, Semicolon separator, CRLF line endings
 *
 * IMPORTANT: Does NOT silently drop assignments with missing blocks.
 * Instead, includes them as placeholder rows marked "[DATEN FEHLEN]".
 *
 * Returns data quality report for UI display.
 */
export function exportToCSV(
    assignments: AssignmentOutput[],
    filename: string = "schedule_export",
    runId?: string
): DataQualityReport {
    const BOM = "\uFEFF";
    const SEPARATOR = ";";
    const LINE_END = "\r\n";

    // Analyze data quality first
    const qualityReport = analyzeAssignments(assignments);

    // Log run context for traceability
    if (qualityReport.has_data_loss && runId) {
        console.error(`[DATA QUALITY] Run ID: ${runId} has ${qualityReport.missing_block_count} missing blocks`);
    }

    // Header
    const headers = [
        "Fahrer-ID",
        "Name",
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Gesamtstunden",
        "Status", // New column for data quality
    ];

    // Build driver map - include ALL assignments, mark missing ones
    const driverMap = new Map<
        string,
        {
            id: string;
            name: string;
            total: number;
            days: Record<string, string>;
            hasMissingData: boolean;
            missingDays: string[];
        }
    >();

    const dayMapping: Record<string, string> = {
        Mon: "Montag",
        Tue: "Dienstag",
        Wed: "Mittwoch",
        Thu: "Donnerstag",
        Fri: "Freitag",
        Sat: "Samstag",
        MONDAY: "Montag",
        TUESDAY: "Dienstag",
        WEDNESDAY: "Mittwoch",
        THURSDAY: "Donnerstag",
        FRIDAY: "Freitag",
        SATURDAY: "Samstag",
    };

    assignments.forEach((a) => {
        if (!driverMap.has(a.driver_id)) {
            driverMap.set(a.driver_id, {
                id: a.driver_id,
                name: a.driver_name,
                total: 0,
                days: {},
                hasMissingData: false,
                missingDays: [],
            });
        }
        const d = driverMap.get(a.driver_id)!;
        const dayKey = dayMapping[a.day] || a.day;

        if (!a.block) {
            // INCLUDE missing blocks as placeholder - NEVER drop
            d.hasMissingData = true;
            d.missingDays.push(dayKey);
            d.days[dayKey] = "[DATEN FEHLEN]";
        } else {
            d.total += a.block.total_work_hours ?? 0;
            const tours = a.block.tours ?? [];
            const tourStr = tours
                .map((t) => `${t.start_time}-${t.end_time}`)
                .join(", ");
            const existing = d.days[dayKey] || "";
            d.days[dayKey] = existing ? `${existing} | ${tourStr}` : tourStr;
        }
    });

    // Build CSV content
    let content = BOM;
    content += headers.join(SEPARATOR) + LINE_END;

    Array.from(driverMap.values())
        .sort((a, b) => a.id.localeCompare(b.id))
        .forEach((d) => {
            const status = d.hasMissingData
                ? `UNVOLLSTÄNDIG (${d.missingDays.join(", ")})`
                : "OK";
            const row = [
                escapeCSV(d.id),
                escapeCSV(d.name),
                escapeCSV(d.days["Montag"] || ""),
                escapeCSV(d.days["Dienstag"] || ""),
                escapeCSV(d.days["Mittwoch"] || ""),
                escapeCSV(d.days["Donnerstag"] || ""),
                escapeCSV(d.days["Freitag"] || ""),
                escapeCSV(d.days["Samstag"] || ""),
                d.total.toFixed(2).replace(".", ","), // German decimal
                escapeCSV(status),
            ];
            content += row.join(SEPARATOR) + LINE_END;
        });

    // Add data quality summary at end of file if there are issues
    if (qualityReport.has_data_loss) {
        content += LINE_END;
        content += `# DATENQUALITÄT WARNUNG${LINE_END}`;
        content += `# Fehlende Blöcke: ${qualityReport.missing_block_count} von ${qualityReport.total_assignments}${LINE_END}`;
        if (runId) {
            content += `# Run ID: ${runId}${LINE_END}`;
        }
    }

    // Trigger download
    const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `${filename}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    return qualityReport;
}

function escapeCSV(value: string): string {
    if (value.includes(";") || value.includes('"') || value.includes("\n")) {
        return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
}

// =============================================================================
// MATRIX VIEW CONVERSION
// =============================================================================

export interface DriverRowsResult {
    rows: DriverRow[];
    qualityReport: DataQualityReport;
}

/**
 * Convert assignments to MatrixView DriverRow format
 *
 * IMPORTANT: Does NOT silently drop assignments with missing blocks.
 * Instead, marks them with "[?]" indicator.
 *
 * Returns both rows and data quality report for UI display.
 */
export function assignmentsToDriverRows(
    assignments: AssignmentOutput[]
): DriverRowsResult {
    const qualityReport = analyzeAssignments(assignments);

    const driverMap = new Map<
        string,
        {
            id: string;
            name: string;
            total: number;
            days: Record<string, string>;
        }
    >();

    const dayMapping: Record<string, keyof DriverRow> = {
        Mon: "monday",
        Tue: "tuesday",
        Wed: "wednesday",
        Thu: "thursday",
        Fri: "friday",
        Sat: "saturday",
        MONDAY: "monday",
        TUESDAY: "tuesday",
        WEDNESDAY: "wednesday",
        THURSDAY: "thursday",
        FRIDAY: "friday",
        SATURDAY: "saturday",
    };

    assignments.forEach((a) => {
        if (!driverMap.has(a.driver_id)) {
            driverMap.set(a.driver_id, {
                id: a.driver_id,
                name: a.driver_name,
                total: 0,
                days: {},
            });
        }
        const d = driverMap.get(a.driver_id)!;
        const dayKey = dayMapping[a.day];

        if (!a.block) {
            // Mark missing data visually - NEVER silently drop
            if (dayKey) {
                d.days[dayKey as string] = "[?] DATEN FEHLEN";
            }
        } else {
            d.total += a.block.total_work_hours ?? 0;
            if (dayKey) {
                const blockType = a.block.block_type ?? "UNKNOWN";
                const tours = a.block.tours ?? [];
                const tourStr = tours
                    .map((t) => `${t.start_time}-${t.end_time}`)
                    .join(" ");
                d.days[dayKey as string] = `[${blockType}] ${tourStr}`;
            }
        }
    });

    const rows = Array.from(driverMap.values())
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((d) => ({
            driverId: d.id,
            driverName: d.name,
            monday: d.days["monday"] || "",
            tuesday: d.days["tuesday"] || "",
            wednesday: d.days["wednesday"] || "",
            thursday: d.days["thursday"] || "",
            friday: d.days["friday"] || "",
            saturday: d.days["saturday"] || "",
            totalHours: d.total,
        }));

    return { rows, qualityReport };
}

// =============================================================================
// LEGACY WRAPPER (for backward compatibility)
// =============================================================================

/**
 * @deprecated Use assignmentsToDriverRows() which returns DataQualityReport
 */
export function assignmentsToDriverRowsLegacy(
    assignments: AssignmentOutput[]
): DriverRow[] {
    return assignmentsToDriverRows(assignments).rows;
}
