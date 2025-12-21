// frontend_v2/src/utils/importToursCsv.ts
export type TourInput = {
    id: string;
    day: "Mon" | "Tue" | "Wed" | "Thu" | "Fri" | "Sat" | "Sun";
    start_time: string; // "HH:MM"
    end_time: string; // "HH:MM"
    required_qualifications?: string[];
};

const DAY_MAP: Record<string, TourInput["day"]> = {
    montag: "Mon",
    dienstag: "Tue",
    mittwoch: "Wed",
    donnerstag: "Thu",
    freitag: "Fri",
    samstag: "Sat",
    sonntag: "Sun",
    // English variants
    monday: "Mon",
    tuesday: "Tue",
    wednesday: "Wed",
    thursday: "Thu",
    friday: "Fri",
    saturday: "Sat",
    sunday: "Sun",
    // Short forms
    mon: "Mon",
    tue: "Tue",
    wed: "Wed",
    thu: "Thu",
    fri: "Fri",
    sat: "Sat",
    sun: "Sun",
};

function normalizeHeader(h: string): string {
    // remove weird leading chars like "...Donnerstag"
    return h.replace(/^[^A-Za-zÄÖÜäöüß]+/g, "").trim().toLowerCase();
}

function padTime(t: string): string {
    // accepts "4:45" or "04:45"
    const [h, m] = t.trim().split(":");
    const hh = String(parseInt(h, 10)).padStart(2, "0");
    const mm = String(parseInt(m, 10)).padStart(2, "0");
    return `${hh}:${mm}`;
}

function parseTimeRange(v: string): { start: string; end: string } | null {
    const s = String(v ?? "").trim();
    const m = s.match(/^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$/);
    if (!m) return null;
    return { start: padTime(m[1]), end: padTime(m[2]) };
}

function minutes(t: string): number {
    const [h, m] = t.split(":").map((x) => parseInt(x, 10));
    return h * 60 + m;
}

function durationHours(start: string, end: string): number {
    let d = minutes(end) - minutes(start);
    if (d < 0) d += 24 * 60; // overnight safety
    return d / 60.0;
}

function splitLines(text: string): string[] {
    return text
        .replace(/^\uFEFF/, "")
        .split(/\r?\n/)
        .filter((l) => l.trim().length > 0);
}

// Very small CSV splitter for ; or , (no nested quoted delimiters)
// Good enough for your current matrix files.
function splitCsvLine(line: string, delim: string): string[] {
    const out: string[] = [];
    let cur = "";
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '"') {
            inQuotes = !inQuotes;
            continue;
        }
        if (!inQuotes && ch === delim) {
            out.push(cur.trim());
            cur = "";
            continue;
        }
        cur += ch;
    }
    out.push(cur.trim());
    return out;
}

export type CsvImportResult = {
    tours: TourInput[];
    stats: { toursCount: number; totalHours: number };
    warnings: string[];
};

export async function importToursFromCsvFile(file: File): Promise<CsvImportResult> {
    const text = await file.text();
    const lines = splitLines(text);
    const warnings: string[] = [];

    if (lines.length < 2) {
        return { tours: [], stats: { toursCount: 0, totalHours: 0 }, warnings: ["CSV ist leer oder hat nur Header"] };
    }

    // Detect delimiter
    const headerLine = lines[0];
    const delim = headerLine.includes(";") ? ";" : ",";

    const headersRaw = splitCsvLine(headerLine, delim);
    const headersNorm = headersRaw.map(normalizeHeader);

    // Format B: list format
    const hasListFormat =
        headersNorm.includes("day") &&
        headersNorm.includes("start_time") &&
        headersNorm.includes("end_time");

    const tours: TourInput[] = [];
    let skippedRows = 0;

    if (hasListFormat) {
        const idxDay = headersNorm.indexOf("day");
        const idxStart = headersNorm.indexOf("start_time");
        const idxEnd = headersNorm.indexOf("end_time");
        const idxCount = headersNorm.indexOf("count");

        for (let r = 1; r < lines.length; r++) {
            const cols = splitCsvLine(lines[r], delim);
            const dayRaw = (cols[idxDay] ?? "").trim().toLowerCase();
            const day = DAY_MAP[dayRaw] ?? null;
            if (!day) {
                skippedRows++;
                continue;
            }

            const start = padTime(cols[idxStart] ?? "");
            const end = padTime(cols[idxEnd] ?? "");
            const c = idxCount >= 0 ? parseInt(cols[idxCount] ?? "1", 10) : 1;
            const count = Number.isFinite(c) ? Math.max(0, c) : 1;

            for (let k = 1; k <= count; k++) {
                const id = `${day}_${start.replace(":", "")}_${end.replace(":", "")}_${String(k).padStart(2, "0")}`;
                tours.push({ id, day, start_time: start, end_time: end });
            }
        }

        if (skippedRows > 0) {
            warnings.push(`${skippedRows} Zeile(n) ohne gültigen Tag übersprungen`);
        }
    } else {
        // Format A: matrix format (German weekday columns + "Anzahl" next col)
        // Build (dayColIndex -> countColIndex)
        const pairs: Array<{
            day: TourInput["day"];
            idxTime: number;
            idxCount: number;
        }> = [];

        for (let i = 0; i < headersNorm.length; i++) {
            const hn = headersNorm[i];
            if (hn in DAY_MAP) {
                const idxTime = i;
                const idxCount = i + 1 < headersNorm.length ? i + 1 : -1;
                pairs.push({ day: DAY_MAP[hn], idxTime, idxCount });
            }
        }

        if (pairs.length === 0) {
            throw new Error(
                "CSV hat keine erkannten Wochentag-Spalten (Montag…Samstag/Sonntag oder Monday…Sunday)."
            );
        }

        let rowsWithoutTimeRange = 0;
        let cellsWithZeroCount = 0;

        for (let r = 1; r < lines.length; r++) {
            const cols = splitCsvLine(lines[r], delim);
            let foundAny = false;

            for (const p of pairs) {
                const tr = cols[p.idxTime];
                const parsed = parseTimeRange(tr);
                if (!parsed) continue;
                foundAny = true;

                const countRaw = p.idxCount >= 0 ? cols[p.idxCount] : "0";
                const count = Math.max(
                    0,
                    parseInt(String(countRaw ?? "0").trim() || "0", 10)
                );
                if (!count) {
                    cellsWithZeroCount++;
                    continue;
                }

                for (let k = 1; k <= count; k++) {
                    const id = `${p.day}_${parsed.start.replace(":", "")}_${parsed.end.replace(":", "")}_${String(k).padStart(2, "0")}`;
                    tours.push({
                        id,
                        day: p.day,
                        start_time: parsed.start,
                        end_time: parsed.end,
                    });
                }
            }

            if (!foundAny) {
                rowsWithoutTimeRange++;
            }
        }

        if (rowsWithoutTimeRange > 0) {
            warnings.push(`${rowsWithoutTimeRange} Zeile(n) ohne gültigen time-range ignoriert`);
        }
        if (cellsWithZeroCount > 0) {
            warnings.push(`${cellsWithZeroCount} Zelle(n) mit Anzahl=0 übersprungen`);
        }
    }

    // deterministic ordering
    tours.sort((a, b) =>
        (a.day + a.start_time + a.end_time + a.id).localeCompare(
            b.day + b.start_time + b.end_time + b.id
        )
    );

    const totalHours = tours.reduce(
        (sum, t) => sum + durationHours(t.start_time, t.end_time),
        0
    );

    return {
        tours,
        stats: {
            toursCount: tours.length,
            totalHours: Math.round(totalHours * 10) / 10,
        },
        warnings,
    };
}
