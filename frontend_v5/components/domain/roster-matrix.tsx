import { RosterRow } from "@/lib/types";
import { ShiftPill } from "./shift-pill";
import { cn } from "@/lib/utils";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const driverTypeBadges: Record<string, { bg: string; text: string }> = {
    'FTE': { bg: 'bg-blue-600', text: 'text-white' },
    'PT_core': { bg: 'bg-violet-500', text: 'text-white' },
    'PT_flex': { bg: 'bg-slate-500', text: 'text-white' },
};

interface RosterMatrixProps {
    data: RosterRow[];
    isLoading?: boolean;
}

export function RosterMatrix({ data, isLoading }: RosterMatrixProps) {
    if (isLoading) {
        return (
            <div className="p-12 text-center">
                <div className="inline-flex items-center gap-3 text-slate-400">
                    <div className="w-5 h-5 border-2 border-slate-600 border-t-slate-300 rounded-full animate-spin" />
                    <span className="text-sm font-medium">Loading roster...</span>
                </div>
            </div>
        );
    }

    if (!data?.length) {
        return (
            <div className="p-12 text-center border-2 border-dashed border-slate-700 rounded-xl bg-slate-800/30">
                <div className="text-slate-500 text-sm font-medium">No roster data available</div>
            </div>
        );
    }

    return (
        <div className="border border-slate-700 rounded-lg overflow-hidden bg-slate-800/50">
            <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                    {/* Header */}
                    <thead>
                        <tr className="bg-slate-800 border-b border-slate-700">
                            <th className="px-4 py-3 text-left font-semibold text-slate-300 text-xs uppercase tracking-wide sticky left-0 bg-slate-800 z-20 min-w-[200px] border-r border-slate-700">
                                Driver
                            </th>
                            <th className="px-3 py-3 text-center font-semibold text-slate-300 text-xs uppercase tracking-wide w-16 border-r border-slate-700/50">
                                Type
                            </th>
                            <th className="px-3 py-3 text-center font-semibold text-slate-300 text-xs uppercase tracking-wide w-14 border-r border-slate-700/50">
                                Hrs
                            </th>
                            {DAYS.map((d, i) => (
                                <th
                                    key={d}
                                    className={cn(
                                        "px-1 py-3 text-center font-semibold text-slate-300 text-xs uppercase tracking-wide w-20",
                                        i < DAYS.length - 1 && "border-r border-slate-700/30"
                                    )}
                                >
                                    {d}
                                </th>
                            ))}
                        </tr>
                    </thead>

                    {/* Body */}
                    <tbody className="divide-y divide-slate-700/50">
                        {data.map((row, rowIdx) => {
                            const badge = driverTypeBadges[row.driver_type] || driverTypeBadges['PT_flex'];
                            const isEven = rowIdx % 2 === 0;

                            return (
                                <tr
                                    key={row.driver_id}
                                    className={cn(
                                        "group transition-colors h-12",
                                        isEven ? "bg-slate-800/30" : "bg-slate-800/50",
                                        "hover:bg-slate-700/50"
                                    )}
                                >
                                    {/* Driver Name - Sticky */}
                                    <td className={cn(
                                        "px-4 py-1.5 sticky left-0 z-10 border-r border-slate-700",
                                        isEven ? "bg-slate-800/30" : "bg-slate-800/50",
                                        "group-hover:bg-slate-700/50"
                                    )}>
                                        <div className="flex flex-col">
                                            <span className="font-medium text-slate-200 text-sm truncate max-w-[180px]">
                                                {row.driver_name}
                                            </span>
                                            <span className="text-[10px] text-slate-500 font-mono tabular-nums">
                                                {row.driver_id}
                                            </span>
                                        </div>
                                    </td>

                                    {/* Driver Type Badge */}
                                    <td className="px-2 py-1.5 text-center border-r border-slate-700/50">
                                        <span className={cn(
                                            "inline-flex items-center justify-center px-1.5 py-0.5 rounded text-[9px] font-bold min-w-[36px]",
                                            badge.bg, badge.text
                                        )}>
                                            {row.driver_type === 'PT_core' ? 'Core' : row.driver_type === 'PT_flex' ? 'Flex' : 'FTE'}
                                        </span>
                                    </td>

                                    {/* Weekly Hours */}
                                    <td className="px-2 py-1.5 text-center border-r border-slate-700/50">
                                        <span className={cn(
                                            "font-mono text-xs tabular-nums",
                                            row.weekly_hours >= 40 ? "text-slate-200 font-semibold" : "text-slate-400"
                                        )}>
                                            {row.weekly_hours.toFixed(0)}
                                        </span>
                                    </td>

                                    {/* Shift Cells */}
                                    {row.shifts.map((shift, idx) => (
                                        <td
                                            key={idx}
                                            className={cn(
                                                "px-0 py-0 h-12",
                                                idx < DAYS.length - 1 && "border-r border-slate-700/20"
                                            )}
                                        >
                                            {shift ? (
                                                <ShiftPill shift={shift} />
                                            ) : (
                                                <div className="w-full h-full flex items-center justify-center">
                                                    <span className="w-1 h-1 rounded-full bg-slate-600" />
                                                </div>
                                            )}
                                        </td>
                                    ))}
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
