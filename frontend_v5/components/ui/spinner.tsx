import * as React from "react";
import { cn, cva, type VariantProps } from "@/lib/utils";

const spinnerVariants = cva(
    "animate-spin rounded-full border-2 border-current border-t-transparent",
    {
        variants: {
            size: {
                xs: "h-3 w-3",
                sm: "h-4 w-4",
                default: "h-6 w-6",
                lg: "h-8 w-8",
                xl: "h-12 w-12",
            },
            variant: {
                default: "text-primary",
                white: "text-white",
                muted: "text-foreground-muted",
            },
        },
        defaultVariants: {
            size: "default",
            variant: "default",
        },
    }
);

export interface SpinnerProps
    extends React.HTMLAttributes<HTMLDivElement>,
        VariantProps<typeof spinnerVariants> {
    label?: string;
}

function Spinner({ className, size, variant, label, ...props }: SpinnerProps) {
    return (
        <div
            className={cn("inline-flex items-center gap-2", className)}
            role="status"
            aria-label={label || "Loading"}
            {...props}
        >
            <div className={cn(spinnerVariants({ size, variant }))} />
            {label && (
                <span className="text-sm text-foreground-muted">{label}</span>
            )}
            <span className="sr-only">{label || "Loading..."}</span>
        </div>
    );
}

// Full-page loading overlay
function LoadingOverlay({
    label = "Loading...",
    className,
}: {
    label?: string;
    className?: string;
}) {
    return (
        <div
            className={cn(
                "fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm",
                className
            )}
        >
            <div className="flex flex-col items-center gap-4">
                <Spinner size="xl" />
                <p className="text-sm font-medium text-foreground-muted">{label}</p>
            </div>
        </div>
    );
}

// Inline loading state for buttons or small areas
function LoadingDots({ className }: { className?: string }) {
    return (
        <span className={cn("inline-flex gap-1", className)}>
            <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse [animation-delay:0ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse [animation-delay:150ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse [animation-delay:300ms]" />
        </span>
    );
}

export { Spinner, spinnerVariants, LoadingOverlay, LoadingDots };
