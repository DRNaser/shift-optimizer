
import { Shift, ValidationError } from '../types';

const timeRegex = /^([01]\d|2[0-3]):([0-5]\d)$/;
const validDays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const timeToMinutes = (time: string): number => {
  const [hours, minutes] = time.split(':').map(Number);
  return hours * 60 + minutes;
};

export const validateShifts = (shifts: any): ValidationError | null => {
  if (!Array.isArray(shifts)) {
    return {
      status: 'error',
      reason: 'invalid_input',
      details: ['Request body must be an array of shift objects.'],
    };
  }

  const errors: string[] = [];

  for (let i = 0; i < shifts.length; i++) {
    const shift = shifts[i];
    const shiftIdentifier = `Shift at index ${i} (Day: ${shift.day || 'N/A'}, Start: ${shift.start || 'N/A'})`;

    if (typeof shift !== 'object' || shift === null) {
      errors.push(`Item at index ${i} is not a valid object.`);
      continue;
    }

    if (!shift.day || !validDays.includes(shift.day)) {
      errors.push(`${shiftIdentifier}: Invalid or missing 'day'. Must be one of: ${validDays.join(', ')}.`);
    }
    if (!shift.start || !timeRegex.test(shift.start)) {
      errors.push(`${shiftIdentifier}: Invalid or missing 'start' time. Must be in HH:MM format.`);
    }
    if (!shift.end || !timeRegex.test(shift.end)) {
      errors.push(`${shiftIdentifier}: Invalid or missing 'end' time. Must be in HH:MM format.`);
    }
    
    if (timeRegex.test(shift.start) && timeRegex.test(shift.end)) {
        if (timeToMinutes(shift.start) >= timeToMinutes(shift.end)) {
            errors.push(`${shiftIdentifier}: Start time must be before end time.`);
        }
    }
  }

  if (errors.length > 0) {
    return {
      status: 'error',
      reason: 'invalid_time',
      details: errors,
    };
  }

  return null;
};
