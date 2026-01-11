import * as React from "react";
import { cn, cva, type VariantProps } from "@/lib/utils";

const badgeVariants = cva(
    "inline-flex items-center rounded-full font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
    {
        variants: {
            variant: {
                default: "bg-primary/10 text-primary border border-primary/20",
                secondary: "bg-muted text-foreground-muted border border-border",
                success: "bg-success-light text-success border border-success/20",
                warning: "bg-warning-light text-warning border border-warning/20",
                error: "bg-error-light text-error border border-error/20",
                info: "bg-info-light text-info border border-info/20",
                outline: "border border-border text-foreground",
                // Solid variants for higher contrast
                "solid-primary": "bg-primary text-white",
                "solid-success": "bg-success text-white",
                "solid-warning": "bg-warning text-white",
                "solid-error": "bg-error text-white",
            },
            size: {
                sm: "px-2 py-0.5 text-xs",
                default: "px-2.5 py-0.5 text-xs",
                lg: "px-3 py-1 text-sm",
            },
        },
        defaultVariants: {
            variant: "default",
            size: "default",
        },
    }
);

export interface BadgeProps
    extends React.HTMLAttributes<HTMLDivElement>,
        VariantProps<typeof badgeVariants> {
    dot?: boolean;
}

function Badge({ className, variant, size, dot, children, ...props }: BadgeProps) {
    return (
        <div className={cn(badgeVariants({ variant, size }), className)} {...props}>
            {dot && (
                <span
                    className={cn(
                        "mr-1.5 h-1.5 w-1.5 rounded-full",
                        variant === "success" || variant === "solid-success"
                            ? "bg-success"
                            : variant === "warning" || variant === "solid-warning"
                            ? "bg-warning"
                            : variant === "error" || variant === "solid-error"
                            ? "bg-error"
                            : variant === "info"
                            ? "bg-info"
                            : "bg-primary"
                    )}
                />
            )}
            {children}
        </div>
    );
}

export { Badge, badgeVariants };
