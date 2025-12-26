import type { AssignmentOutput } from "./api";
import type { DriverRow } from "@/components/ui/matrix-view";

/**
 * Master Export - V5 Contract
 * UTF-8 BOM, Semicolon separator, CRLF line endings
 */
export function exportToCSV(
    assignments: AssignmentOutput[],
    filename: string = "schedule_export"
): void {
    const BOM = "\uFEFF";
    const SEPARATOR = ";";
    const LINE_END = "\r\n";

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
    ];

    // Build driver map
    const driverMap = new Map<
        string,
        {
            id: string;
            name: string;
            total: number;
            days: Record<string, string>;
        }
    >();

    const dayMapping: Record<string, string> = {
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
            });
        }
        const d = driverMap.get(a.driver_id)!;
        d.total += a.block.total_work_hours;

        const dayKey = dayMapping[a.day] || a.day;
        const tourStr = a.block.tours
            .map((t) => `${t.start_time}-${t.end_time}`)
            .join(", ");
        const existing = d.days[dayKey] || "";
        d.days[dayKey] = existing ? `${existing} | ${tourStr}` : tourStr;
    });

    // Build CSV content
    let content = BOM;
    content += headers.join(SEPARATOR) + LINE_END;

    Array.from(driverMap.values())
        .sort((a, b) => a.id.localeCompare(b.id))
        .forEach((d) => {
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
            ];
            content += row.join(SEPARATOR) + LINE_END;
        });

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
}

function escapeCSV(value: string): string {
    if (value.includes(";") || value.includes('"') || value.includes("\n")) {
        return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
}

/**
 * Convert assignments to MatrixView DriverRow format
 */
export function assignmentsToDriverRows(
    assignments: AssignmentOutput[]
): DriverRow[] {
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
        d.total += a.block.total_work_hours;

        const dayKey = dayMapping[a.day];
        if (dayKey) {
            const blockType = a.block.block_type;
            const tourStr = a.block.tours
                .map((t) => `${t.start_time}-${t.end_time}`)
                .join(" ");
            d.days[dayKey as string] = `[${blockType}] ${tourStr}`;
        }
    });

    return Array.from(driverMap.values())
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
}
