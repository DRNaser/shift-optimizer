import * as React from "react";
import { cn } from "@/lib/utils";

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
    variant?: "default" | "circular" | "text" | "card";
}

function Skeleton({ className, variant = "default", ...props }: SkeletonProps) {
    const variants = {
        default: "rounded-lg",
        circular: "rounded-full",
        text: "rounded h-4 w-full",
        card: "rounded-xl h-32",
    };

    return (
        <div
            className={cn(
                "animate-shimmer bg-muted",
                variants[variant],
                className
            )}
            {...props}
        />
    );
}

// Pre-built skeleton components for common use cases
function SkeletonCard({ className }: { className?: string }) {
    return (
        <div className={cn("rounded-xl border border-border bg-card p-6 space-y-4", className)}>
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
            <div className="space-y-2">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-4/5" />
            </div>
        </div>
    );
}

function SkeletonAvatar({ size = "default" }: { size?: "sm" | "default" | "lg" }) {
    const sizes = {
        sm: "h-8 w-8",
        default: "h-10 w-10",
        lg: "h-14 w-14",
    };
    return <Skeleton variant="circular" className={sizes[size]} />;
}

function SkeletonButton({ size = "default" }: { size?: "sm" | "default" | "lg" }) {
    const sizes = {
        sm: "h-9 w-20",
        default: "h-10 w-24",
        lg: "h-12 w-32",
    };
    return <Skeleton className={cn("rounded-lg", sizes[size])} />;
}

function SkeletonTable({ rows = 5 }: { rows?: number }) {
    return (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
            {/* Header */}
            <div className="border-b border-border bg-muted/50 p-4 flex gap-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 flex-1" />
            </div>
            {/* Rows */}
            {Array.from({ length: rows }).map((_, i) => (
                <div key={i} className="border-b border-border last:border-0 p-4 flex gap-4 items-center">
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-4 w-20" />
                    <Skeleton className="h-4 flex-1" />
                </div>
            ))}
        </div>
    );
}

function SkeletonKPICard() {
    return (
        <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <div className="flex items-center gap-2">
                <Skeleton variant="circular" className="h-8 w-8" />
                <Skeleton className="h-3 w-20" />
            </div>
            <Skeleton className="h-8 w-16" />
        </div>
    );
}

export { Skeleton, SkeletonCard, SkeletonAvatar, SkeletonButton, SkeletonTable, SkeletonKPICard };
