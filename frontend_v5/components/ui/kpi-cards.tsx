"use client";

import { Activity, Cpu, Zap } from "lucide-react";

interface KPICardsProps {
    driversFTE: number;
    driversPT: number;
    utilization: number;
    gapToLB: number;
    totalHours: number;
    isLoading?: boolean;
}

export function KPICards({
    driversFTE,
    driversPT,
    utilization,
    gapToLB,
    totalHours,
    isLoading = false,
}: KPICardsProps) {
    const cards = [
        {
            label: "FTE Drivers",
            value: driversFTE,
            format: (v: number) => v.toFixed(1),
            icon: Cpu,
            color: "text-blue-400",
            bgColor: "bg-blue-500/10",
        },
        {
            label: "PT Drivers",
            value: driversPT,
            format: (v: number) => v.toString(),
            icon: Activity,
            color: "text-emerald-400",
            bgColor: "bg-emerald-500/10",
        },
        {
            label: "Utilization",
            value: utilization * 100,
            format: (v: number) => `${v.toFixed(1)}%`,
            icon: Zap,
            color: "text-amber-400",
            bgColor: "bg-amber-500/10",
        },
        {
            label: "Gap to LB",
            value: gapToLB * 100,
            format: (v: number) => (v === 0 ? "OPTIMAL" : `${v.toFixed(1)}%`),
            icon: Zap,
            color: gapToLB === 0 ? "text-emerald-400" : "text-slate-400",
            bgColor: gapToLB === 0 ? "bg-emerald-500/10" : "bg-slate-500/10",
        },
    ];

    if (isLoading) {
        return (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[1, 2, 3, 4].map((i) => (
                    <div
                        key={i}
                        className="bg-slate-900 border border-slate-800 rounded-lg p-4 animate-pulse"
                    >
                        <div className="h-4 bg-slate-800 rounded w-24 mb-3" />
                        <div className="h-8 bg-slate-800 rounded w-16" />
                    </div>
                ))}
            </div>
        );
    }

    return (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {cards.map((card) => (
                <div
                    key={card.label}
                    className="bg-slate-900 border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors"
                >
                    <div className="flex items-center gap-2 mb-2">
                        <div className={`p-1.5 rounded ${card.bgColor}`}>
                            <card.icon className={`w-4 h-4 ${card.color}`} />
                        </div>
                        <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                            {card.label}
                        </span>
                    </div>
                    <div className={`text-2xl font-bold ${card.color}`}>
                        {card.format(card.value)}
                    </div>
                </div>
            ))}
        </div>
    );
}
