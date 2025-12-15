"""
SHIFT OPTIMIZER - FastAPI Application
======================================
Main entry point for the backend API.

This is the production API server.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router


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
    - Max 14.5h daily span
    - Max 3 tours per day
    - Min 11h rest between days
    - No tour overlaps
    - Qualification requirements
    - Availability requirements
    """,
    version="1.0.0",
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
