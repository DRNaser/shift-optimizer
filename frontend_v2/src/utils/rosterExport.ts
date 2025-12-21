import * as XLSX from "xlsx";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

type AnyPlan = any;

function pad2(n: number) {
    return String(n).padStart(2, "0");
}

function timeToHHMM(t: any): string | null {
    // supports "HH:MM" string or {hour, minute}
    if (!t) return null;
    if (typeof t === "string") return t.slice(0, 5);
    if (typeof t.hour === "number" && typeof t.minute === "number")
        return `${pad2(t.hour)}:${pad2(t.minute)}`;
    return null;
}

function getBlockStartEnd(block: any): { start: string | null; end: string | null } {
    const start =
        timeToHHMM(block.first_start) ||
        timeToHHMM(block.start_time) ||
        timeToHHMM(block.start);
    const end =
        timeToHHMM(block.last_end) ||
        timeToHHMM(block.end_time) ||
        timeToHHMM(block.end);
    // fallback from tours
    if ((!start || !end) && Array.isArray(block.tours) && block.tours.length) {
        const sorted = [...block.tours].sort((a, b) =>
            String(a.start_time || a.start) < String(b.start_time || b.start) ? -1 : 1
        );
        const s = timeToHHMM(sorted[0].start_time || sorted[0].start);
        const e = timeToHHMM(
            sorted[sorted.length - 1].end_time || sorted[sorted.length - 1].end
        );
        return { start: start ?? s, end: end ?? e };
    }
    return { start, end };
}

function getBlockHours(block: any): number {
    // tries total_work_hours, else minutes->hours, else sum from tours
    if (typeof block.total_work_hours === "number") return block.total_work_hours;
    if (typeof block.total_work_minutes === "number")
        return Math.round((block.total_work_minutes / 60) * 100) / 100;
    if (Array.isArray(block.tours)) {
        let mins = 0;
        for (const t of block.tours) {
            if (typeof t.duration_minutes === "number") mins += t.duration_minutes;
            else if (typeof t.duration_hours === "number")
                mins += t.duration_hours * 60;
        }
        return Math.round((mins / 60) * 100) / 100;
    }
    return 0;
}

function normalizePlan(plan: AnyPlan): Array<{
    driver_id: string;
    driver_type?: string;
    blocks: any[];
}> {
    // Supports:
    // 1) plan.drivers[] {driver_id,type,blocks[]}
    // 2) plan.assignments[] {driver_id, day, block:{...}}
    if (Array.isArray(plan?.drivers)) {
        return plan.drivers
            .filter((d: any) => d && d.driver_id)
            .map((d: any) => ({
                driver_id: d.driver_id,
                driver_type: d.type ?? d.driver_type,
                blocks: d.blocks ?? [],
            }));
    }
    if (Array.isArray(plan?.assignments)) {
        const map = new Map<string, any>();
        for (const a of plan.assignments) {
            const did = a.driver_id;
            if (!did) continue;
            if (!map.has(did))
                map.set(did, {
                    driver_id: did,
                    driver_type: a.driver_type ?? a.type,
                    blocks: [],
                });
            const blk = a.block ?? a;
            // ensure day on block
            if (!blk.day && a.day) blk.day = a.day;
            map.get(did).blocks.push(blk);
        }
        return Array.from(map.values());
    }
    return [];
}

function safeDay(block: any): string {
    const d = block?.day?.value ?? block?.day;
    if (!d) return "";
    // allow "Monday" -> Mon etc
    const s = String(d);
    if (DAYS.includes(s as any)) return s;
    const key = s.toLowerCase().slice(0, 3);
    const map: Record<string, string> = {
        mon: "Mon",
        tue: "Tue",
        wed: "Wed",
        thu: "Thu",
        fri: "Fri",
        sat: "Sat",
        sun: "Sun",
    };
    return map[key] ?? s;
}

export function buildRosterExportData(plan: AnyPlan) {
    const drivers = normalizePlan(plan);

    // deterministic sorting
    drivers.sort((a, b) => a.driver_id.localeCompare(b.driver_id));

    // Long rows (Shifts)
    const shifts: any[] = [];

    // Matrix rows
    const matrixRows: any[] = [];

    for (const d of drivers) {
        const byDay: Record<string, any[]> = {};
        for (const day of DAYS) byDay[day] = [];

        // Blocks sort: (day, start, id)
        const blocks = [...(d.blocks ?? [])].sort((x, y) => {
            const dx = safeDay(x);
            const dy = safeDay(y);
            if (dx !== dy) return dx.localeCompare(dy);
            const sx = getBlockStartEnd(x).start ?? "";
            const sy = getBlockStartEnd(y).start ?? "";
            if (sx !== sy) return sx.localeCompare(sy);
            return String(x.id ?? "").localeCompare(String(y.id ?? ""));
        });

        let totalHours = 0;

        for (const b of blocks) {
            const day = safeDay(b);
            const { start, end } = getBlockStartEnd(b);
            const hours = getBlockHours(b);
            totalHours += hours;

            const blockId = String(b.id ?? "");
            const tours = Array.isArray(b.tours) ? b.tours : [];
            const toursIds = tours
                .map((t: any) => t.id)
                .filter(Boolean)
                .join(",");

            // add to long export
            shifts.push({
                driver_id: d.driver_id,
                driver_type: d.driver_type ?? "",
                day,
                block_id: blockId,
                start: start ?? "",
                end: end ?? "",
                work_hours: Number(hours.toFixed(2)),
                tours_count: tours.length,
                tours_ids: toursIds,
            });

            // add to matrix
            if (DAYS.includes(day as any)) {
                byDay[day].push(
                    `${start ?? ""}-${end ?? ""} (${hours.toFixed(2)}h) [${blockId}]`
                );
            }
        }

        const row: any = {
            driver_id: d.driver_id,
            driver_type: d.driver_type ?? "",
        };

        for (const day of DAYS) {
            row[day] = byDay[day].join(" | ");
        }
        row["Total Hours"] = Number(totalHours.toFixed(2));
        matrixRows.push(row);
    }

    return { matrixRows, shifts };
}

export function exportRosterXlsx(params: {
    plan: AnyPlan;
    report?: any;
    filename?: string;
    bullets?: Array<{ label: string; status: "GOOD" | "WARN" | "BAD"; value?: string }>;
}) {
    const { matrixRows, shifts } = buildRosterExportData(params.plan);

    const wb = XLSX.utils.book_new();

    // Sheet: RosterMatrix
    const wsMatrix = XLSX.utils.json_to_sheet(matrixRows);
    XLSX.utils.book_append_sheet(wb, wsMatrix, "RosterMatrix");

    // Sheet: Shifts
    const wsShifts = XLSX.utils.json_to_sheet(shifts);
    XLSX.utils.book_append_sheet(wb, wsShifts, "Shifts");

    // Sheet: Summary (optional)
    const summaryRows: any[] = [];
    if (params.bullets?.length) {
        summaryRows.push({ KPI: "Result Check", Value: "" });
        for (const b of params.bullets) {
            summaryRows.push({
                KPI: `${b.status} - ${b.label}`,
                Value: b.value ?? "",
            });
        }
    }
    if (params.report?.kpi) {
        summaryRows.push({ KPI: "KPI Raw", Value: "" });
        for (const [k, v] of Object.entries(params.report.kpi)) {
            summaryRows.push({
                KPI: String(k),
                Value: typeof v === "object" ? JSON.stringify(v) : String(v),
            });
        }
    }
    if (summaryRows.length) {
        const wsSum = XLSX.utils.json_to_sheet(summaryRows);
        XLSX.utils.book_append_sheet(wb, wsSum, "Summary");
    }

    const filename = params.filename ?? "roster_export.xlsx";
    const out = XLSX.write(wb, { bookType: "xlsx", type: "array" });

    const blob = new Blob([out], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}
