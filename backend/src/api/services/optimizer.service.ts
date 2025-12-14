
import { Shift, OptimizationResult, Driver, Segment } from '../types';

const PAUSE_DURATION = 30; // 30 minutes

const timeToMinutes = (time: string): number => {
  const [hours, minutes] = time.split(':').map(Number);
  return hours * 60 + minutes;
};

const minutesToTime = (minutes: number): string => {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
};

const calculateTotalHours = (segments: Segment[]): number => {
  const totalMinutes = segments.reduce((acc, segment) => {
    return acc + (timeToMinutes(segment.end) - timeToMinutes(segment.start));
  }, 0);
  return parseFloat((totalMinutes / 60).toFixed(2));
};

const optimizeDay = (dayShifts: Shift[]): { threeBlocks: Shift[][]; twoBlocks: Shift[][]; oneBlocks: Shift[][] } => {
  const sortedShifts = [...dayShifts].sort((a, b) => timeToMinutes(a.start) - timeToMinutes(b.start));
  const used = new Array(sortedShifts.length).fill(false);
  
  const threeBlocks: Shift[][] = [];
  const twoBlocks: Shift[][] = [];
  const oneBlocks: Shift[][] = [];

  // 3-Block Pass
  for (let i = 0; i < sortedShifts.length; i++) {
    if (used[i]) continue;
    for (let j = i + 1; j < sortedShifts.length; j++) {
      if (used[j]) continue;
      if (timeToMinutes(sortedShifts[j].start) === timeToMinutes(sortedShifts[i].end) + PAUSE_DURATION) {
        for (let k = j + 1; k < sortedShifts.length; k++) {
          if (used[k]) continue;
          if (timeToMinutes(sortedShifts[k].start) === timeToMinutes(sortedShifts[j].end) + PAUSE_DURATION) {
            threeBlocks.push([sortedShifts[i], sortedShifts[j], sortedShifts[k]]);
            used[i] = used[j] = used[k] = true;
            break; 
          }
        }
      }
      if (used[i]) break;
    }
  }

  // 2-Block Pass
  for (let i = 0; i < sortedShifts.length; i++) {
    if (used[i]) continue;
    for (let j = i + 1; j < sortedShifts.length; j++) {
      if (used[j]) continue;
      if (timeToMinutes(sortedShifts[j].start) === timeToMinutes(sortedShifts[i].end) + PAUSE_DURATION) {
        twoBlocks.push([sortedShifts[i], sortedShifts[j]]);
        used[i] = used[j] = true;
        break;
      }
    }
  }

  // 1-Block Pass
  for (let i = 0; i < sortedShifts.length; i++) {
    if (!used[i]) {
      oneBlocks.push([sortedShifts[i]]);
    }
  }

  return { threeBlocks, twoBlocks, oneBlocks };
};


export const optimizeShifts = (shifts: Shift[]): OptimizationResult => {
  const shiftsByDay: Record<string, Shift[]> = shifts.reduce((acc, shift) => {
    if (!acc[shift.day]) {
      acc[shift.day] = [];
    }
    acc[shift.day].push(shift);
    return acc;
  }, {} as Record<string, Shift[]>);

  const drivers: Driver[] = [];
  let driverIdCounter = 1;
  let totalShiftsOutput = 0;

  const stats = {
    total_drivers_used: 0,
    total_shifts_input: shifts.length,
    total_shifts_output: 0,
    "3er_count": 0,
    "2er_count": 0,
    "1er_count": 0,
  };

  for (const day in shiftsByDay) {
    const { threeBlocks, twoBlocks, oneBlocks } = optimizeDay(shiftsByDay[day]);
    
    threeBlocks.forEach(block => {
      drivers.push({
        driver_id: driverIdCounter++,
        day,
        block_type: '3er',
        segments: block.map(s => ({ start: s.start, end: s.end })),
        total_hours: calculateTotalHours(block),
      });
      stats["3er_count"]++;
      totalShiftsOutput += 3;
    });

    twoBlocks.forEach(block => {
      drivers.push({
        driver_id: driverIdCounter++,
        day,
        block_type: '2er',
        segments: block.map(s => ({ start: s.start, end: s.end })),
        total_hours: calculateTotalHours(block),
      });
      stats["2er_count"]++;
      totalShiftsOutput += 2;
    });

    oneBlocks.forEach(block => {
      drivers.push({
        driver_id: driverIdCounter++,
        day,
        block_type: '1er',
        segments: block.map(s => ({ start: s.start, end: s.end })),
        total_hours: calculateTotalHours(block),
      });
      stats["1er_count"]++;
      totalShiftsOutput += 1;
    });
  }
  
  stats.total_drivers_used = drivers.length;
  stats.total_shifts_output = totalShiftsOutput;

  // The 'unused' array is conceptually tricky with this algorithm, as it uses all valid inputs.
  // It would only be populated if the input validation rejected some shifts, which it does upfront.
  // So, it remains empty in this implementation.
  const unused: Shift[] = [];

  return { drivers, stats, unused };
};
