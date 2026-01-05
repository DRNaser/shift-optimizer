# SOLVEREIGN V3.3a API

Production-ready REST API for shift scheduling optimization.

## Features

- **Multi-Tenant**: Full tenant isolation with API key authentication
- **Idempotent**: Safe request retries via X-Idempotency-Key
- **Concurrent-Safe**: PostgreSQL advisory locks prevent duplicate solves
- **Observable**: Structured JSON logging, Prometheus metrics ready
- **Type-Safe**: Pydantic models for all requests/responses

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export SOLVEREIGN_DATABASE_URL=postgresql://user:pass@localhost:5432/solvereign
export SOLVEREIGN_ENVIRONMENT=development

# Run migrations
psql $DATABASE_URL < db/migrations/006_multi_tenant.sql
psql $DATABASE_URL < db/migrations/007_idempotency_keys.sql
psql $DATABASE_URL < db/migrations/008_tour_segments.sql
psql $DATABASE_URL < db/migrations/009_plan_versions_extended.sql

# Start server
uvicorn api.main:app --reload
```

## API Endpoints

### Health
- `GET /health` - Liveness check
- `GET /health/ready` - Readiness check with dependencies
- `GET /health/live` - Simple alive check

### Tenants
- `GET /api/v1/tenants/me` - Current tenant info
- `GET /api/v1/tenants/me/stats` - Usage statistics

### Forecasts
- `POST /api/v1/forecasts` - Ingest new forecast
- `GET /api/v1/forecasts` - List forecasts (paginated)
- `GET /api/v1/forecasts/{id}` - Forecast details

### Plans
- `POST /api/v1/plans/solve` - Solve forecast
- `GET /api/v1/plans/{id}` - Plan status
- `GET /api/v1/plans/{id}/kpis` - Plan KPIs
- `GET /api/v1/plans/{id}/audit` - Audit results
- `POST /api/v1/plans/{id}/lock` - Lock for release
- `GET /api/v1/plans/{id}/export/{format}` - Export plan

## Authentication

All API endpoints (except /health) require X-API-Key header:

```bash
curl -H "X-API-Key: your-api-key-here" \
     http://localhost:8000/api/v1/tenants/me
```

## Idempotency

For POST requests, include X-Idempotency-Key header:

```bash
curl -X POST \
     -H "X-API-Key: your-api-key" \
     -H "X-Idempotency-Key: unique-request-id" \
     -H "Content-Type: application/json" \
     -d '{"raw_text": "Mo 08:00-16:00"}' \
     http://localhost:8000/api/v1/forecasts
```

## Configuration

Environment variables (prefix: `SOLVEREIGN_`):

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | postgresql://... | PostgreSQL connection |
| ENVIRONMENT | development | development/staging/production |
| LOG_LEVEL | INFO | DEBUG/INFO/WARNING/ERROR |
| LOG_FORMAT | json | json/text |
| HOST | 0.0.0.0 | Server bind address |
| PORT | 8000 | Server port |
| SOLVER_TIMEOUT_SECONDS | 300 | Solver timeout |
| IDEMPOTENCY_TTL_HOURS | 24 | Idempotency key TTL |

## Project Structure

```
api/
├── main.py              # FastAPI application
├── config.py            # Pydantic settings
├── database.py          # Async PostgreSQL pool
├── dependencies.py      # FastAPI dependencies
├── exceptions.py        # Custom exceptions
├── logging_config.py    # Structured logging
├── routers/
│   ├── health.py        # Health endpoints
│   ├── tenants.py       # Tenant endpoints
│   ├── forecasts.py     # Forecast endpoints
│   └── plans.py         # Plan endpoints
├── repositories/
│   ├── base.py          # Base repository
│   ├── forecasts.py     # Forecast data access
│   ├── plans.py         # Plan data access
│   └── tenants.py       # Tenant data access
├── ADR-001-multi-tenant.md
├── ADR-002-advisory-locks.md
├── ADR-003-idempotency.md
└── requirements.txt
```

## Migrations

Execute in order:

1. `006_multi_tenant.sql` - Tenants table, tenant_id on all tables
2. `007_idempotency_keys.sql` - Idempotency support
3. `008_tour_segments.sql` - Segment adapter pattern
4. `009_plan_versions_extended.sql` - Extended state machine

## Development

```bash
# Run tests
pytest api/tests/ -v

# Format code
black api/
isort api/

# Type check
mypy api/
```

## License

Proprietary - LTS Transport u. Logistik GmbH
