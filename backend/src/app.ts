
import express, { Express, Request, Response } from 'express';
import cors from 'cors';
import optimizeRoutes from './api/routes/optimize.routes';

const app: Express = express();

app.use(cors());
app.use(express.json());

app.get('/', (req: Request, res: Response) => {
  res.send('Shift Optimizer API is running!');
});

app.use('/optimize', optimizeRoutes);

export default app;
