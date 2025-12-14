// Types for SHIFT OPTIMIZER API v2
// Matches new Python backend structure

// =============================================================================
// ENUMS
// =============================================================================

export type Weekday = 'MONDAY' | 'TUESDAY' | 'WEDNESDAY' | 'THURSDAY' | 'FRIDAY' | 'SATURDAY' | 'SUNDAY';

export type BlockType = 'single' | 'double' | 'triple';

export type SolverType = 'greedy' | 'cpsat' | 'cpsat+lns';

export type ReasonCode =
  | 'DRIVER_WEEKLY_LIMIT'
  | 'DRIVER_DAILY_SPAN'
  | 'DRIVER_TOURS_PER_DAY'
  | 'DRIVER_BLOCKS_PER_DAY'
  | 'DRIVER_REST_TIME'
  | 'DRIVER_NOT_AVAILABLE'
  | 'DRIVER_QUALIFICATION_MISSING'
  | 'TOUR_OVERLAP'
  | 'NO_AVAILABLE_DRIVER'
  | 'INFEASIBLE';

// =============================================================================
// INPUT TYPES
// =============================================================================

export interface TourInput {
  id: string;
  day: Weekday;
  start_time: string;  // HH:MM
  end_time: string;    // HH:MM
  location?: string;
  required_qualifications?: string[];
}

export interface DriverInput {
  id: string;
  name: string;
  qualifications?: string[];
  max_weekly_hours?: number;
  max_daily_span_hours?: number;
  max_tours_per_day?: number;
  min_rest_hours?: number;
  available_days?: Weekday[];
}

export interface ScheduleRequest {
  tours: TourInput[];
  drivers: DriverInput[];
  week_start: string;  // YYYY-MM-DD
  prefer_larger_blocks?: boolean;
  seed?: number | null;
  solver_type?: SolverType;
  time_limit_seconds?: number;
  lns_iterations?: number;
  locked_block_ids?: string[];
}

// =============================================================================
// OUTPUT TYPES
// =============================================================================

export interface TourOutput {
  id: string;
  day: string;
  start_time: string;
  end_time: string;
  duration_hours: number;
  location: string;
  required_qualifications: string[];
}

export interface BlockOutput {
  id: string;
  day: string;
  block_type: BlockType;
  tours: TourOutput[];
  driver_id: string | null;
  total_work_hours: number;
  span_hours: number;
}

export interface AssignmentOutput {
  driver_id: string;
  driver_name: string;
  day: string;
  block: BlockOutput;
}

export interface UnassignedTourOutput {
  tour: TourOutput;
  reason_codes: ReasonCode[];
  details: string;
}

export interface StatsOutput {
  total_drivers: number;
  total_tours_input: number;
  total_tours_assigned: number;
  total_tours_unassigned: number;
  block_counts: Record<string, number>;
  assignment_rate: number;
  average_driver_utilization: number;
}

export interface ValidationOutput {
  is_valid: boolean;
  hard_violations: string[];
  warnings: string[];
}

export interface ScheduleResponse {
  id: string;
  week_start: string;
  assignments: AssignmentOutput[];
  unassigned_tours: UnassignedTourOutput[];
  validation: ValidationOutput;
  stats: StatsOutput;
  version: string;
  solver_type: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  constraints: Record<string, number | boolean>;
}

export interface ApiError {
  status: 'error';
  message: string;
  details: string[];
}

// =============================================================================
// UI STATE TYPES
// =============================================================================

export interface ScheduleState {
  request: ScheduleRequest | null;
  response: ScheduleResponse | null;
  isLoading: boolean;
  error: ApiError | null;
}

// Helper to get color for block type
export function getBlockTypeColor(blockType: BlockType): string {
  switch (blockType) {
    case 'triple': return '#22c55e';  // green
    case 'double': return '#3b82f6';  // blue
    case 'single': return '#f59e0b';  // amber
    default: return '#6b7280';        // gray
  }
}

// Helper to get reason code description
export function getReasonDescription(code: ReasonCode): string {
  const descriptions: Record<ReasonCode, string> = {
    'DRIVER_WEEKLY_LIMIT': 'Driver would exceed weekly hours limit',
    'DRIVER_DAILY_SPAN': 'Daily span would be too long',
    'DRIVER_TOURS_PER_DAY': 'Too many tours in one day',
    'DRIVER_BLOCKS_PER_DAY': 'Driver already has a block this day',
    'DRIVER_REST_TIME': 'Insufficient rest time between days',
    'DRIVER_NOT_AVAILABLE': 'Driver not available on this day',
    'DRIVER_QUALIFICATION_MISSING': 'Driver lacks required qualification',
    'TOUR_OVERLAP': 'Tour overlaps with another',
    'NO_AVAILABLE_DRIVER': 'No driver available for this tour',
    'INFEASIBLE': 'No feasible assignment found',
  };
  return descriptions[code] || code;
}

// Days of week in order
export const WEEKDAYS: Weekday[] = [
  'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'
];

// Short day names for UI
export const DAY_SHORT: Record<Weekday, string> = {
  'MONDAY': 'Mo',
  'TUESDAY': 'Di',
  'WEDNESDAY': 'Mi',
  'THURSDAY': 'Do',
  'FRIDAY': 'Fr',
  'SATURDAY': 'Sa',
  'SUNDAY': 'So',
};
