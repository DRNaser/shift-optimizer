# ShiftOptimizer Frontend v2.0

Modern Next.js UI for the ShiftOptimizer scheduling system.

## Features

- **Schema-driven Setup**: Configuration form generated from `/v1/config-schema`
- **Live Run Monitoring**: Real-time SSE event streaming with reconnect
- **Results Dashboard**: Plan table with filters, config audit trail, downloads

## Tech Stack

- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- Zustand (state management)

## Getting Started

```bash
# Install dependencies
npm install

# Copy environment file
cp .env.example .env.local

# Edit .env.local to set your API URL
# NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api

# Start development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Screens

### Screen A — Setup (`/`)

1. Loads config schema from API
2. Generates controls for each field:
   - `bool` → Toggle
   - `float/int` → Slider with min/max
   - Locked fields → Disabled + tooltip
3. Tours input: JSON textarea + file upload
4. Request preview before submit
5. Submits `POST /v1/runs` and redirects to live screen

### Screen B — Live Run (`/runs/[id]`)

1. Polls `GET /v1/runs/{id}` every 2s
2. Connects to `GET /v1/runs/{id}/events` (SSE)
3. Displays:
   - Current phase + budget slices
   - Live logs with level filter
   - Reason codes
   - Connection indicator + heartbeat
4. Cancel button
5. Auto-redirect to results on completion

### Screen C — Results (`/runs/[id]/results`)

1. Fetches report, canonical, and plan in parallel
2. Overview tab:
   - Stats cards (drivers, tours, rate, hours)
   - Block distribution
   - Timing breakdown
   - Reason codes
   - Validation status
3. Assignments tab:
   - Filterable table (driver type, block type, day)
   - Underfull FTE filter
   - Stable sort
4. Config tab:
   - Effective config hash
   - Applied overrides
   - Rejected overrides with reasons
   - Clamped values
5. Download buttons for all JSON outputs

## API Endpoints Used

Only these 8 endpoints from the v2.0 API:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/config-schema` | UI metadata |
| POST | `/v1/runs` | Create run |
| GET | `/v1/runs/{id}` | Status + links |
| GET | `/v1/runs/{id}/events` | SSE stream |
| GET | `/v1/runs/{id}/report` | Full report |
| GET | `/v1/runs/{id}/report/canonical` | Stable JSON |
| GET | `/v1/runs/{id}/plan` | Assignments |
| POST | `/v1/runs/{id}/cancel` | Cancel run |

## SSE Event Handling

The UI handles these event types:

- `run_started` — Extract budget slices
- `run_snapshot` — Replace event buffer on reconnect
- `phase_started`, `phase_progress` — Update phase indicator
- `solver_log` — Display in console
- `heartbeat` — Update connection indicator
- `run_completed`, `run_failed`, `run_cancelled` — Trigger navigation

Reconnection with exponential backoff is implemented. The `Last-Event-ID` header is automatically sent by the browser's `EventSource`.

## Configuration Display

The UI transparently shows how configuration was processed:

1. **Effective Config Hash**: Unique identifier for the exact config used
2. **Applied Overrides**: What the user requested that was accepted
3. **Rejected Overrides**: What was rejected + reason (e.g., `LOCKED_FIELD`)
4. **Clamped Values**: What was adjusted to fit within bounds

This ensures the user always knows what config was actually used.
