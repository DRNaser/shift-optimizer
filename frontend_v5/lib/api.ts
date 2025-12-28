
// Use relative path - Next.js rewrites proxy it to localhost:8000
const API_BASE = "/api/v1";

// --- Types ---

export interface TourInput {
    id: string;
    day: string; // MONDAY, TUESDAY, etc. (Weekday enum value)
    start_time: string; // HH:MM format
    end_time: string; // HH:MM format
}

export interface DriverInput {
    id: string;
    name: string;
    qualifications: string[];
    available_days: string[];
    max_weekly_hours: number;
}

export interface RunCreateRequest {
    tours: TourInput[];
    drivers: DriverInput[];
    week_start: string; // YYYY-MM-DD
    run: {
        time_budget_seconds: number;
        seed: number;
        config_overrides: {
            output_profile?: string; // MIN_HEADCOUNT_3ER or BEST_BALANCED
        };
    };
}

export interface RunCreateResponse {
    run_id: string;
    status: string;
    run_url: string;
}

export interface RunStatusResponse {
    run_id: string;
    status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
    phase?: string;
    budget?: {
        total: number;
        status: string;
    };
}

export interface StatsOutput {
    total_drivers: number;
    total_tours_input: number;
    total_tours_assigned: number;
    total_tours_unassigned: number;
    block_counts: Record<string, number>;
    assignment_rate: number;
    average_driver_utilization: number;
    average_work_hours: number;
    drivers_fte: number;
    drivers_pt: number;
    total_hours?: number;
}

export interface BlockOutput {
    id: string;
    day: string;
    block_type: string;
    tours: {
        id: string;
        day: string;
        start_time: string;
        end_time: string;
        duration_hours: number;
    }[];
    driver_id: string | null;
    total_work_hours: number;
    span_hours: number;
    pause_zone: string;
}

export interface AssignmentOutput {
    driver_id: string;
    driver_name: string;
    day: string;
    block: BlockOutput;
}

export interface UnassignedTourOutput {
    tour: {
        id: string;
        day: string;
        start_time: string;
        end_time: string;
    };
    reason_codes: string[];
    details: string;
}

export interface ScheduleResponse {
    id: string;
    week_start: string;
    assignments: AssignmentOutput[];
    unassigned_tours: UnassignedTourOutput[];
    stats: StatsOutput;
    validation: {
        is_valid: boolean;
        hard_violations: string[];
    };
}

// --- API Client ---

export async function createRun(
    tours: TourInput[],
    drivers?: DriverInput[],
    timeBudget: number = 120  // Default: Fast mode (120s)
): Promise<RunCreateResponse> {
    const driverList = drivers && drivers.length > 0 ? drivers : generateDefaultDrivers();

    const payload: RunCreateRequest = {
        tours,
        drivers: driverList,
        week_start: "2024-01-01",
        run: {
            time_budget_seconds: timeBudget,
            seed: 42,
            config_overrides: {
                output_profile: "MIN_HEADCOUNT_3ER",
            },
        },
    };


    // Debug: Log payload before sending
    console.log("🚀 Submitting Payload to Backend:", JSON.stringify(payload, null, 2));
    console.log(`📊 Tours count: ${tours.length}, First tour:`, tours[0]);

    const res = await fetch(`${API_BASE}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    if (!res.ok) {
        // Try to parse error body
        let errorData: any = {};
        try {
            const text = await res.text();
            if (text) {
                errorData = JSON.parse(text);
            }
        } catch {
            // Response wasn't JSON
        }

        console.error(`❌ Backend Error [HTTP ${res.status}]:`, errorData);

        // Handle FastAPI Pydantic validation errors (422)
        if (res.status === 422 && errorData.detail && Array.isArray(errorData.detail)) {
            const validationErrors = errorData.detail.map((e: any) =>
                `${e.loc?.join(".")} -> ${e.msg} (input: ${JSON.stringify(e.input)})`
            );
            console.error("🔴 VALIDATION ERRORS:", validationErrors);
            throw new Error(`Validation Failed:\n${validationErrors.join("\n")}`);
        }

        // Build error message
        let errorMsg = `HTTP ${res.status}`;
        if (errorData.detail) {
            if (typeof errorData.detail === "string") {
                errorMsg = errorData.detail;
            } else if (Array.isArray(errorData.detail)) {
                errorMsg = errorData.detail.map((e: any) => `${e.loc?.join(".")}: ${e.msg}`).join("; ");
            } else {
                errorMsg = JSON.stringify(errorData.detail);
            }
        } else if (Object.keys(errorData).length > 0) {
            errorMsg = JSON.stringify(errorData);
        } else {
            errorMsg = `HTTP ${res.status}: Backend unreachable or CORS blocked. Is the server running on port 8000?`;
        }
        throw new Error(errorMsg);
    }

    return res.json();
}

export async function getRunStatus(runId: string): Promise<RunStatusResponse> {
    const res = await fetch(`${API_BASE}/runs/${runId}`);
    if (!res.ok) throw new Error(`Get Status failed: ${res.status}`);
    return res.json();
}

export async function getRunResult(runId: string): Promise<ScheduleResponse> {
    const res = await fetch(`${API_BASE}/runs/${runId}/plan`);
    if (!res.ok) throw new Error(`Get Result failed: ${res.status}`);
    return res.json();
}

// --- Helpers ---

// Global Day Mapping - Backend expects ONLY: Mon, Tue, Wed, Thu, Fri, Sat, Sun
const VALID_DAYS: Record<string, string> = {
    'MONDAY': 'Mon', 'Monday': 'Mon', 'Montag': 'Mon', 'Mon': 'Mon',
    'TUESDAY': 'Tue', 'Tuesday': 'Tue', 'Dienstag': 'Tue', 'Tue': 'Tue',
    'WEDNESDAY': 'Wed', 'Wednesday': 'Wed', 'Mittwoch': 'Wed', 'Wed': 'Wed',
    'THURSDAY': 'Thu', 'Thursday': 'Thu', 'Donnerstag': 'Thu', 'Thu': 'Thu',
    'FRIDAY': 'Fri', 'Friday': 'Fri', 'Freitag': 'Fri', 'Fri': 'Fri',
    'SATURDAY': 'Sat', 'Saturday': 'Sat', 'Samstag': 'Sat', 'Sat': 'Sat',
    'SUNDAY': 'Sun', 'Sunday': 'Sun', 'Sonntag': 'Sun', 'Sun': 'Sun',
};

function normalizeDay(day: string): string {
    return VALID_DAYS[day] || day;
}

function generateDefaultDrivers(): DriverInput[] {
    const drivers: DriverInput[] = [];

    // 200 FTEs (virtual pool)
    for (let i = 1; i <= 200; i++) {
        drivers.push({
            id: `FTE-${i}`,
            name: `FTE Driver ${i}`,
            qualifications: ["standard"],
            available_days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
            max_weekly_hours: 53,
        });
    }

    // 200 PTs (virtual pool)
    for (let i = 1; i <= 200; i++) {
        drivers.push({
            id: `PT-${i}`,
            name: `PT Driver ${i}`,
            qualifications: ["standard"],
            available_days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
            max_weekly_hours: 24,
        });
    }

    return drivers;
}

/**
 * Parse "forecast input neu.csv" Matrix Format
 * Columns: Montag;Anzahl;Dienstag;Anzahl.1;Mittwoch;Anzahl.2;...
 * Rows: Time windows like "04:45-09:15" with counts
 */
export function parseCSV(content: string): TourInput[] {
    const lines = content
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => l.length > 0);

    if (lines.length < 2) return [];

    const tours: TourInput[] = [];
    // Backend Weekday enum uses abbreviated values: Mon, Tue, Wed, Thu, Fri, Sat, Sun
    const dayOrder = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

    // Skip header row (line 0), process data rows
    for (let rowIdx = 1; rowIdx < lines.length; rowIdx++) {
        const cols = lines[rowIdx].split(";");

        // Process each day pair (timeWindow, count)
        for (let dayIdx = 0; dayIdx < dayOrder.length; dayIdx++) {
            const timeColIdx = dayIdx * 2;
            const countColIdx = dayIdx * 2 + 1;

            const timeWindow = cols[timeColIdx]?.trim();
            const countStr = cols[countColIdx]?.trim();

            if (!timeWindow || !countStr) continue;
            if (!timeWindow.includes("-")) continue;

            // Parse count (handle German comma decimals like "6,0")
            const count = parseInt(countStr.replace(",", "."), 10);
            if (isNaN(count) || count <= 0) continue;

            // Parse time window
            const timeParts = timeWindow.split("-");
            if (timeParts.length !== 2) continue;

            const startTime = normalizeTime(timeParts[0].trim());
            const endTime = normalizeTime(timeParts[1].trim());

            if (!startTime || !endTime) continue;

            // Generate tours for this count
            for (let c = 0; c < count; c++) {
                tours.push({
                    id: `T-${rowIdx}-${dayIdx}-${c}`,
                    day: dayOrder[dayIdx],
                    start_time: startTime,
                    end_time: endTime,
                });
            }
        }
    }

    return tours;
}

/**
 * Normalize time to HH:MM format (required by backend regex)
 */
function normalizeTime(time: string): string | null {
    const match = time.match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return null;
    const hours = match[1].padStart(2, "0");
    const minutes = match[2];
    return `${hours}:${minutes}`;
}

