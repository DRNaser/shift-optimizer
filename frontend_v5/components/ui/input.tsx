import * as React from "react";
import { cn, cva, type VariantProps } from "@/lib/utils";

const inputVariants = cva(
    "flex w-full rounded-lg border bg-input text-foreground transition-all duration-200 file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-foreground-muted focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
    {
        variants: {
            variant: {
                default:
                    "border-input-border focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary",
                filled:
                    "border-transparent bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:bg-input focus-visible:border-primary",
                ghost:
                    "border-transparent bg-transparent hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
                error:
                    "border-error focus-visible:ring-2 focus-visible:ring-error/50 focus-visible:border-error",
            },
            inputSize: {
                sm: "h-9 px-3 text-sm",
                default: "h-10 px-4 text-sm",
                lg: "h-12 px-4 text-base",
            },
        },
        defaultVariants: {
            variant: "default",
            inputSize: "default",
        },
    }
);

export interface InputProps
    extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size">,
        VariantProps<typeof inputVariants> {
    leftIcon?: React.ReactNode;
    rightIcon?: React.ReactNode;
    error?: boolean;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, type, variant, inputSize, leftIcon, rightIcon, error, ...props }, ref) => {
        const effectiveVariant = error ? "error" : variant;

        if (leftIcon || rightIcon) {
            return (
                <div className="relative flex items-center w-full">
                    {leftIcon && (
                        <div className="absolute left-3 flex items-center pointer-events-none text-foreground-muted">
                            {leftIcon}
                        </div>
                    )}
                    <input
                        type={type}
                        className={cn(
                            inputVariants({ variant: effectiveVariant, inputSize, className }),
                            leftIcon && "pl-10",
                            rightIcon && "pr-10"
                        )}
                        ref={ref}
                        {...props}
                    />
                    {rightIcon && (
                        <div className="absolute right-3 flex items-center pointer-events-none text-foreground-muted">
                            {rightIcon}
                        </div>
                    )}
                </div>
            );
        }

        return (
            <input
                type={type}
                className={cn(inputVariants({ variant: effectiveVariant, inputSize, className }))}
                ref={ref}
                {...props}
            />
        );
    }
);
Input.displayName = "Input";

export { Input, inputVariants };
