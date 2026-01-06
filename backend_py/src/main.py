"""
SOLVEREIGN - Legacy API (V6)
============================
Main entry point for the legacy backend API.

Note: Enterprise API is at api/main.py (V3.3b)
This legacy API is kept for backwards compatibility.
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
    logging.info("SOLVEREIGN Legacy API v6.0 started")
    print("INFO: Legacy API started. For Enterprise API, use api.main:app", flush=True)


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
