"use client";

import { cn } from "@/lib/utils";
import { Check } from "lucide-react";

interface PipelineStep {
    id: number;
    name: string;
    duration?: string;
    status: "completed" | "active" | "pending";
    detail?: string;
}

interface PipelineStepperProps {
    steps: PipelineStep[];
    className?: string;
}

export function PipelineStepper({ steps, className }: PipelineStepperProps) {
    return (
        <div className={cn("w-full", className)}>
            {/* Steps */}
            <div className="flex items-start justify-between relative">
                {steps.map((step, idx) => {
                    const isLast = idx === steps.length - 1;

                    return (
                        <div key={step.id} className="flex-1 flex flex-col items-center relative">
                            {/* Connector Line */}
                            {!isLast && (
                                <div className="absolute top-4 left-1/2 w-full h-0.5 bg-slate-700">
                                    <div
                                        className={cn(
                                            "h-full transition-all duration-500",
                                            step.status === "completed" ? "bg-emerald-500 w-full" : "w-0"
                                        )}
                                    />
                                </div>
                            )}

                            {/* Step Circle */}
                            <div className={cn(
                                "relative z-10 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all",
                                step.status === "completed" && "bg-emerald-500 text-white",
                                step.status === "active" && "bg-blue-600 text-white ring-4 ring-blue-500/30",
                                step.status === "pending" && "bg-slate-700 text-slate-500 border-2 border-slate-600"
                            )}>
                                {step.status === "completed" ? (
                                    <Check className="w-4 h-4" />
                                ) : (
                                    step.id
                                )}
                            </div>

                            {/* Label */}
                            <div className="mt-2 text-center">
                                <div className={cn(
                                    "text-xs font-semibold uppercase tracking-wide",
                                    step.status === "active" ? "text-blue-400" :
                                        step.status === "completed" ? "text-slate-300" : "text-slate-500"
                                )}>
                                    {step.name}
                                </div>
                                {step.duration && (
                                    <div className={cn(
                                        "text-[10px] mt-0.5 tabular-nums",
                                        step.status === "completed" ? "text-emerald-400" : "text-slate-500"
                                    )}>
                                        {step.duration}
                                    </div>
                                )}
                                {step.detail && (
                                    <div className={cn(
                                        "text-[10px] mt-0.5",
                                        step.status === "active" ? "text-amber-400 font-medium" : "text-slate-500"
                                    )}>
                                        {step.detail}
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Progress Bar */}
            <div className="mt-4 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div
                    className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-500 rounded-full"
                    style={{
                        width: `${(steps.filter(s => s.status === "completed").length / steps.length) * 100}%`
                    }}
                />
            </div>
        </div>
    );
}

export function getDefaultPipelineSteps(status: "running" | "completed" | "failed"): PipelineStep[] {
    if (status === "completed") {
        return [
            { id: 1, name: "Block Building", duration: "12s", status: "completed" },
            { id: 2, name: "CP-SAT Selection", duration: "45s", status: "completed" },
            { id: 3, name: "RMP Rounds", duration: "38s", status: "completed" },
            { id: 4, name: "Repair (Bump)", duration: "15s", status: "completed", detail: "+ 12 Actions" },
        ];
    }

    if (status === "failed") {
        return [
            { id: 1, name: "Block Building", duration: "12s", status: "completed" },
            { id: 2, name: "CP-SAT Selection", status: "active", detail: "Failed" },
            { id: 3, name: "RMP Rounds", status: "pending" },
            { id: 4, name: "Repair (Bump)", status: "pending" },
        ];
    }

    return [
        { id: 1, name: "Block Building", duration: "12s", status: "completed" },
        { id: 2, name: "CP-SAT Selection", duration: "45s", status: "completed" },
        { id: 3, name: "RMP Rounds", status: "active", detail: "Round 3..." },
        { id: 4, name: "Repair (Bump)", status: "pending" },
    ];
}
