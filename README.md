# ⚡ Shift Optimizer

**Optimal weekly shift assignment for Last-Mile-Delivery drivers**

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-blue.svg)](https://react.dev)
[![OR-Tools](https://img.shields.io/badge/OR--Tools-CP--SAT-red.svg)](https://developers.google.com/optimization)

## Overview

Shift Optimizer transforms daily tour forecasts into optimal weekly driver assignments using OR-Tools CP-SAT constraint programming. It combines tours into 1er, 2er, or 3er blocks to minimize driver count while respecting all hard constraints.

### Features

- ⚡ **Three Solvers**: Greedy baseline, CP-SAT optimal, CP-SAT+LNS best
- 📊 **Hard Constraints**: Weekly hours, daily span, rest time, qualifications
- 🎯 **Optimization**: Maximize tours, prefer larger blocks, minimize drivers
- 📝 **Explainability**: Reason codes for every unassigned tour
- 🔒 **User Locks**: Lock assignments during refinement
- 🖥️ **Modern UI**: React frontend with week overview grid

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone and run
git clone <repo-url>
cd shift-optimizer
docker compose up --build

# Access
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000/docs
```

### Option 2: Local Development

**Backend:**
```bash
cd backend_py
pip install -r requirements.txt
python -m uvicorn src.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## API Usage

### Create Schedule

```bash
curl -X POST http://localhost:8000/api/v1/schedule \
  -H "Content-Type: application/json" \
  -d '{
    "tours": [
      {"id": "T1", "day": "MONDAY", "start_time": "08:00", "end_time": "12:00"},
      {"id": "T2", "day": "MONDAY", "start_time": "12:30", "end_time": "16:30"}
    ],
    "drivers": [
      {"id": "D1", "name": "Max Mustermann"}
    ],
    "week_start": "2024-01-01",
    "solver_type": "cpsat"
  }'
```

### Solver Options

| Solver | Speed | Quality | Use Case |
|--------|-------|---------|----------|
| `greedy` | ~10ms | Good | Quick previews |
| `cpsat` | ~1-30s | Optimal | Production |
| `cpsat+lns` | ~5-60s | Best | Refinement |

---

## Hard Constraints

| Constraint | Default | Description |
|-----------|---------|-------------|
| `MAX_WEEKLY_HOURS` | 55h | Max hours per driver per week |
| `MAX_DAILY_SPAN_HOURS` | 14.5h | Max span first→last tour |
| `MIN_REST_HOURS` | 11h | Min rest between days |
| `MAX_TOURS_PER_DAY` | 3 | Max tours per driver per day |

---

## Project Structure

```
shift-optimizer/
├── backend_py/              # Python FastAPI + OR-Tools
│   ├── src/
│   │   ├── domain/          # Models, Constraints, Validator
│   │   ├── services/        # Scheduler, CP-SAT, LNS
│   │   └── api/             # Routes, Schemas
│   └── tests/               # 116 unit tests
├── frontend/                # React + Vite + TailwindCSS
│   ├── components/          # UI components
│   └── services/            # API client
└── docker-compose.yml       # Container orchestration
```

---

## Testing

```bash
cd backend_py
python -m pytest tests/ -v
# ============================= 116 passed =============================
```

---

## License

MIT
