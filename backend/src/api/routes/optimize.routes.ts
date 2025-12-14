
import { Router } from 'express';
import { optimizeShiftsController } from '../controllers/optimize.controller';

const router = Router();

router.post('/', optimizeShiftsController);

export default router;
