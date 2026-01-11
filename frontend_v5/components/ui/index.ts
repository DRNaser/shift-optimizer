// Core UI Components - SOLVEREIGN Design System
export { Button, buttonVariants, type ButtonProps } from "./button";
export {
    Card,
    CardHeader,
    CardFooter,
    CardTitle,
    CardDescription,
    CardContent,
    cardVariants,
} from "./card";
export { Input, inputVariants, type InputProps } from "./input";
export { Label } from "./label";
export { Badge, badgeVariants } from "./badge";
export {
    Skeleton,
    SkeletonCard,
    SkeletonAvatar,
    SkeletonButton,
    SkeletonTable,
    SkeletonKPICard,
} from "./skeleton";
export {
    Spinner,
    spinnerVariants,
    LoadingOverlay,
    LoadingDots,
} from "./spinner";
export {
    Avatar,
    AvatarImage,
    AvatarFallback,
    AvatarGroup,
    avatarVariants,
    getInitials,
} from "./avatar";

// Domain-specific components
export { KPICards } from "./kpi-cards";
export { StatusBadge } from "./status-badge";
export { PlanStatusBadge } from "./plan-status-badge";
export { PlatformStatusBadge } from "./platform-status-badge";
export { RunStatusBadge } from "./run-status-badge";
export { Tabs, TabsList, TabsTrigger, TabsContent } from "./tabs";
export { MatrixView } from "./matrix-view";
export { LiveConsole } from "./live-console";
export { ApiError } from "./api-error";
