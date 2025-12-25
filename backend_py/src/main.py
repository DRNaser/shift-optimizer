"""
SHIFT OPTIMIZER - FastAPI Application
======================================
Main entry point for the backend API.

This is the production API server.
"""

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.api.routes_v2 import router_v2


# =============================================================================
# CONFIGURATION
# =============================================================================

# CORS origins: comma-separated list, default to wildcard for development
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


# =============================================================================
# APPLICATION SETUP
# =============================================================================

app = FastAPI(
    title="SHIFT OPTIMIZER API",
    description="""
    Deterministic weekly shift optimizer for Last-Mile-Delivery.
    
    ## Features
    - Rule-based scheduling with hard constraints
    - Greedy feasible-first baseline scheduler
    - Full explainability with reason codes
    - Reproducible results with optional seeding
    
    ## Hard Constraints (Always Enforced)
    - Max 55h/week per driver
    - Max 15.5h daily span
    - Max 3 tours per day
    - Min 11h rest between days
    - No tour overlaps
    - Qualification requirements
    - Availability requirements
    """,
    version="2.0.0",
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

app.include_router(router, prefix="/api/v1", tags=["scheduling"])
app.include_router(router_v2, prefix="/api/v1", tags=["v2-runs"])

# Deprecated: forecast_router conflicts with v2 /runs endpoints.
# To re-enable for local debugging, set ENABLE_FORECAST_ROUTER=true.
if os.getenv("ENABLE_FORECAST_ROUTER", "").lower() in ("1", "true", "yes"):
    logging.getLogger(__name__).warning(
        "forecast_router is deprecated and may collide with /api/v1/runs. "
        "Disable in production."
    )
    from src.api.forecast_router import router as forecast_router
    app.include_router(forecast_router, tags=["forecast"])


@app.on_event("startup")
async def startup_event():
    print("MATCHING_LOG: Using routes_v2 as canonical source", flush=True)


# =============================================================================
# ROOT ENDPOINT
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "SHIFT OPTIMIZER API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "api_base": "/api/v1"
    }


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    # Log startup explicitly for verification
    print("Starting ShiftOptimizer API (RC0 Mode: routes_v2 canonical)...", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8000)
    # Force reload trigger
