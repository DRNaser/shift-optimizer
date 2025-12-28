import { Shift } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * SOLVEREIGN Shift Color Scheme (User Request v7.2.3)
 * - 3er (Long): Orange - Premium long shift
 * - 2er (Regular): Blue - Standard shift
 * - 2er_split: Grey - Split with pause
 * - 1er (Short): Green - Flex filler
 */
const typeStyles: Record<string, { bg: string; hover: string; text: string }> = {
    '3er': {
        bg: 'bg-orange-500',
        hover: 'hover:bg-orange-600',
        text: 'text-white'
    },
    '2er': {
        bg: 'bg-blue-500',
        hover: 'hover:bg-blue-600',
        text: 'text-white'
    },
    '2er_split': {
        bg: 'bg-slate-500',
        hover: 'hover:bg-slate-600',
        text: 'text-white'
    },
    '1er': {
        bg: 'bg-emerald-500',
        hover: 'hover:bg-emerald-600',
        text: 'text-white'
    },
};

export function ShiftPill({ shift }: { shift: Shift }) {
    const style = typeStyles[shift.type] || typeStyles['1er'];

    // SPLIT SHIFT: Two stacked work blocks with visible gap (pause)
    if (shift.is_split) {
        return (
            <div
                className="w-full h-full flex flex-col gap-1 py-1 px-0.5 cursor-default"
                title={`Split: ${shift.start_time} - ${shift.end_time} (Pause dazwischen)`}
            >
                {/* Tour 1 Block */}
                <div className={cn(
                    "flex-1 rounded-sm flex items-center justify-center transition-colors shadow-sm",
                    "bg-slate-500 hover:bg-slate-600"
                )}>
                    <span className="text-[9px] font-bold text-white/90 tracking-tight">AM</span>
                </div>

                {/* Visual Pause Gap - the space represents the break */}

                {/* Tour 2 Block */}
                <div className={cn(
                    "flex-1 rounded-sm flex items-center justify-center transition-colors shadow-sm",
                    "bg-slate-500 hover:bg-slate-600"
                )}>
                    <span className="text-[9px] font-bold text-white/90 tracking-tight">PM</span>
                </div>
            </div>
        );
    }

    // STANDARD SHIFT: Solid rounded block
    return (
        <div className="w-full h-full py-1 px-0.5">
            <div
                className={cn(
                    "w-full h-full rounded-sm flex items-center justify-center transition-colors shadow-sm cursor-default",
                    style.bg,
                    style.hover,
                    style.text
                )}
                title={`${shift.type} | ${shift.start_time} - ${shift.end_time}`}
            >
                <span className="text-[10px] font-bold tracking-tight">{shift.type}</span>
            </div>
        </div>
    );
}
