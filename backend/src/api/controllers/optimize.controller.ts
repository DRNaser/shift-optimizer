
import { Request, Response } from 'express';
import { validateShifts } from '../validators/shift.validator';
import { optimizeShifts } from '../services/optimizer.service';
import { Shift } from '../types';

export const optimizeShiftsController = (req: Request, res: Response) => {
  const shifts: Shift[] = req.body;

  const validationError = validateShifts(shifts);
  if (validationError) {
    return res.status(400).json(validationError);
  }

  try {
    const result = optimizeShifts(shifts);
    return res.status(200).json(result);
  } catch (error) {
    return res.status(500).json({
      status: 'error',
      reason: 'impossible',
      details: [error instanceof Error ? error.message : 'An unexpected error occurred.'],
    });
  }
};
