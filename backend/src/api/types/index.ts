
export interface Shift {
  day: string;
  start: string;
  end: string;
}

export interface Segment {
  start: string;
  end: string;
}

export interface Driver {
  driver_id: number;
  day: string;
  block_type: '1er' | '2er' | '3er';
  segments: Segment[];
  total_hours: number;
}

export interface Stats {
  total_drivers_used: number;
  total_shifts_input: number;
  total_shifts_output: number;
  "3er_count": number;
  "2er_count": number;
  "1er_count": number;
}

export interface OptimizationResult {
  drivers: Driver[];
  stats: Stats;
  unused: Shift[];
}

export interface ValidationError {
  status: 'error';
  reason: 'invalid_time' | 'overlap' | 'impossible' | 'invalid_input';
  details: string[];
}
