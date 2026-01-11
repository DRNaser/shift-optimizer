"use client";

import { Activity, Cpu, Zap, Truck, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "./card";
import { SkeletonKPICard } from "./skeleton";

interface KPICardsProps {
    driversFTE: number;
    driversPT: number;
    utilization: number;
    gapToLB: number;
    totalHours: number;
    fleetPeakCount?: number;
    fleetPeakDay?: string;
    fleetPeakTime?: string;
    isLoading?: boolean;
}

interface KPICardData {
    label: string;
    value: number;
    format: (v: number) => string;
    icon: React.ComponentType<{ className?: string }>;
    color: string;
    bgColor: string;
    glowClass?: string;
    subtitle?: string;
}

function KPICard({ card }: { card: KPICardData }) {
    const isOptimal = card.label === "Gap to LB" && card.value === 0;

    return (
        <Card
            variant="interactive"
            padding="sm"
            className={cn(
                "group relative overflow-hidden",
                isOptimal && "border-success/30"
            )}
        >
            {/* Subtle gradient overlay */}
            <div
                className={cn(
                    "absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300",
                    card.bgColor
                )}
                style={{ opacity: 0.05 }}
            />

            <div className="relative">
                <div className="flex items-center gap-2.5 mb-3">
                    <div
                        className={cn(
                            "p-2 rounded-lg transition-transform group-hover:scale-110",
                            card.bgColor
                        )}
                    >
                        <card.icon className={cn("w-4 h-4", card.color)} />
                    </div>
                    <span className="text-xs font-medium text-foreground-muted uppercase tracking-wider">
                        {card.label}
                    </span>
                </div>

                <div
                    className={cn(
                        "text-2xl font-bold tabular-nums tracking-tight",
                        card.color
                    )}
                >
                    {card.format(card.value)}
                </div>

                {card.subtitle && (
                    <div className="text-xs text-foreground-muted mt-1.5 flex items-center gap-1">
                        <TrendingUp className="w-3 h-3" />
                        {card.subtitle}
                    </div>
                )}
            </div>

            {/* Glow effect for optimal state */}
            {isOptimal && (
                <div className="absolute -inset-px rounded-xl bg-gradient-to-r from-success/20 to-success/5 -z-10" />
            )}
        </Card>
    );
}

export function KPICards({
    driversFTE,
    driversPT,
    utilization,
    gapToLB,
    totalHours,
    fleetPeakCount = 0,
    fleetPeakDay = "",
    fleetPeakTime = "",
    isLoading = false,
}: KPICardsProps) {
    const fleetSubtitle =
        fleetPeakDay && fleetPeakTime ? `${fleetPeakDay} @ ${fleetPeakTime}` : "";

    const cards: KPICardData[] = [
        {
            label: "FTE Drivers",
            value: driversFTE,
            format: (v: number) => v.toString(),
            icon: Cpu,
            color: "text-primary",
            bgColor: "bg-primary/10",
        },
        {
            label: "PT Drivers",
            value: driversPT,
            format: (v: number) => v.toString(),
            icon: Activity,
            color: "text-success",
            bgColor: "bg-success/10",
        },
        {
            label: "Utilization",
            value: utilization * 100,
            format: (v: number) => `${v.toFixed(1)}%`,
            icon: Zap,
            color: "text-warning",
            bgColor: "bg-warning/10",
        },
        {
            label: "Gap to LB",
            value: gapToLB * 100,
            format: (v: number) => (v === 0 ? "OPTIMAL" : `${v.toFixed(1)}%`),
            icon: Zap,
            color: gapToLB === 0 ? "text-success" : "text-foreground-muted",
            bgColor: gapToLB === 0 ? "bg-success/10" : "bg-muted",
        },
        {
            label: "Fleet Peak",
            value: fleetPeakCount,
            format: (v: number) => (v > 0 ? `${v} vehicles` : "N/A"),
            icon: Truck,
            color: "text-accent",
            bgColor: "bg-accent/10",
            subtitle: fleetSubtitle,
        },
    ];

    if (isLoading) {
        return (
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                {[1, 2, 3, 4, 5].map((i) => (
                    <SkeletonKPICard key={i} />
                ))}
            </div>
        );
    }

    return (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 stagger-children">
            {cards.map((card) => (
                <KPICard key={card.label} card={card} />
            ))}
        </div>
    );
}
