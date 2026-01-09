"""
SOLVEREIGN - Legacy API (V6) - DEPRECATED
==========================================

⚠️  DEPRECATED: This API is deprecated in favor of the Enterprise API.
    Please use: uvicorn api.main:app --reload

The Enterprise API (api/main.py) includes ALL features:
- /api/v1/runs/*        - Async optimization with SSE streaming
- /api/v1/plans/*       - Solve, audit, lock, export
- /api/v1/simulations/* - What-If scenarios (8 types)
- /api/v1/config/*      - Configuration schema and validation
- /api/v1/forecasts/*   - Forecast ingest and status

This legacy API is kept ONLY for backwards compatibility during migration.
It will be removed in the next major release.
"""

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# v6.0: Only routes_v2 is used (legacy routes.py and forecast_router.py removed)
from src.api.routes_v2 import router_v2

# V3.3b: Repair API for driver absences
from src.api.repair_router import repair_router

# Structured logging for production observability
from src.utils.structured_logging import get_logger, StructuredFormatter


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

def configure_logging():
    """Configure logging based on environment."""
    log_format = os.getenv("LOG_FORMAT", "console").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(StructuredFormatter(service_name="solvereign"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    
    root_logger.addHandler(handler)

configure_logging()
logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# CORS origins: comma-separated list, default to wildcard for development
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


# =============================================================================
# APPLICATION SETUP
# =============================================================================

app = FastAPI(
    title="SOLVEREIGN API (Legacy)",
    description="""
    SOLVEREIGN Legacy API - Deterministic shift scheduler for Last-Mile-Delivery.

    Note: Use Enterprise API (api/main.py) for production with auth.

    ## Hard Constraints
    - Max 55h/week per driver
    - Max 15.5h daily span
    - Max 3 tours per day
    - Min 11h rest between days
    - No tour overlaps
    """,
    version="6.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


# =============================================================================
# MIDDLEWARE
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTES
# =============================================================================

# v6.0: Single unified API (routes_v2 only)
app.include_router(router_v2, prefix="/api/v1", tags=["runs"])

# V3.3b: Repair API for driver absences
app.include_router(repair_router, prefix="/api/v1", tags=["repair"])


@app.on_event("startup")
async def startup_event():
    logging.warning("⚠️  DEPRECATED: SOLVEREIGN Legacy API v6.0 started")
    logging.warning("⚠️  Please migrate to Enterprise API: uvicorn api.main:app")
    print("", flush=True)
    print("=" * 70, flush=True)
    print("⚠️  DEPRECATED: Legacy API is deprecated!", flush=True)
    print("   Please use Enterprise API instead:", flush=True)
    print("   uvicorn api.main:app --reload", flush=True)
    print("=" * 70, flush=True)
    print("", flush=True)


# =============================================================================
# ROOT ENDPOINT
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "SOLVEREIGN Legacy API",
        "version": "6.0.0",
        "status": "running",
        "docs": "/docs",
        "api_base": "/api/v1",
        "note": "Use Enterprise API (api.main:app) for production"
    }


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    print("Starting SOLVEREIGN Legacy API...", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8000)
