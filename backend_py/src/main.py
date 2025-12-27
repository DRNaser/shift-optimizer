"""
SHIFT OPTIMIZER - FastAPI Application
======================================
Main entry point for the backend API.

This is the production API server (v6.0 - Streamlined).
"""

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# v6.0: Only routes_v2 is used (legacy routes.py and forecast_router.py removed)
from src.api.routes_v2 import router_v2

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
        handler.setFormatter(StructuredFormatter(service_name="shift-optimizer"))
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
    title="SHIFT OPTIMIZER API",
    description="""
    Deterministic weekly shift optimizer for Last-Mile-Delivery.
    
    ## Features
    - Set Partitioning via Column Generation (optimal crew scheduling)
    - Rule-based scheduling with hard constraints
    - Full explainability with reason codes
    - Reproducible results with deterministic seeding
    
    ## Hard Constraints (Always Enforced)
    - Max 55h/week per driver
    - Max 15.5h daily span
    - Max 3 tours per day
    - Min 11h rest between days
    - No tour overlaps
    - Qualification requirements
    - Availability requirements
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


@app.on_event("startup")
async def startup_event():
    logging.info("SHIFT OPTIMIZER API v6.0 started (Set Partitioning Engine)")
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
