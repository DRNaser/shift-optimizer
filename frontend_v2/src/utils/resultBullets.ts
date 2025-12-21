export type Bullet = {
    label: string;
    status: "GOOD" | "WARN" | "BAD";
    value?: string;
};

export function buildResultBullets(report: any, plan: any): Bullet[] {
    const b: Bullet[] = [];
    const kpi = report?.kpi ?? report ?? {};

    const coverage = kpi.coverage_rate ?? kpi.coverage?.rate ?? kpi.coverage_achieved;
    if (typeof coverage === "number") {
        b.push({
            label: "Coverage",
            status: coverage >= 0.995 ? "GOOD" : coverage >= 0.98 ? "WARN" : "BAD",
            value: `${(coverage * 100).toFixed(2)}%`,
        });
    }

    const ptRatio = kpi.pt_ratio ?? kpi.block_mix_ratios?.pt_ratio;
    if (typeof ptRatio === "number") {
        b.push({
            label: "PT Ratio",
            status: ptRatio <= 0.1 ? "GOOD" : ptRatio <= 0.25 ? "WARN" : "BAD",
            value: `${(ptRatio * 100).toFixed(1)}%`,
        });
    }

    const underfull = kpi.underfull_ratio ?? kpi.block_mix_ratios?.underfull_ratio;
    if (typeof underfull === "number") {
        b.push({
            label: "Underfull FTE Ratio",
            status: underfull <= 0.05 ? "GOOD" : underfull <= 0.15 ? "WARN" : "BAD",
            value: `${(underfull * 100).toFixed(1)}%`,
        });
    }

    // Budget Overrun
    const reasonCodes: string[] =
        report?.reason_codes ?? report?.run_report?.reason_codes ?? [];
    const hasOverrun =
        Array.isArray(reasonCodes) && reasonCodes.includes("BUDGET_OVERRUN");
    b.push({
        label: "Budget",
        status: hasOverrun ? "WARN" : "GOOD",
        value: hasOverrun ? "Overrun detected" : "OK",
    });

    // FTE hour range (if available)
    const hMin = kpi.fte_hours_min ?? kpi.hours_min;
    const hMax = kpi.fte_hours_max ?? kpi.hours_max;
    if (typeof hMin === "number" && typeof hMax === "number") {
        const ok = hMin >= 42 && hMax <= 53;
        const warn = hMin >= 40 && hMax <= 56;
        b.push({
            label: "FTE Hours Range",
            status: ok ? "GOOD" : warn ? "WARN" : "BAD",
            value: `${hMin.toFixed(1)}h - ${hMax.toFixed(1)}h`,
        });
    }

    const forced1er = kpi.forced_1er_rate;
    if (typeof forced1er === "number") {
        b.push({
            label: "Forced 1er Rate",
            status: forced1er <= 0.1 ? "GOOD" : forced1er <= 0.25 ? "WARN" : "BAD",
            value: `${(forced1er * 100).toFixed(1)}%`,
        });
    }

    const missed3 = kpi.missed_3er_opps_count;
    if (typeof missed3 === "number") {
        b.push({
            label: "Missed 3er Opportunities",
            status: missed3 <= 10 ? "GOOD" : missed3 <= 50 ? "WARN" : "BAD",
            value: String(missed3),
        });
    }

    return b;
}
