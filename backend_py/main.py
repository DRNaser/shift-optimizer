"""
SHIFT OPTIMIZER API
===================
FastAPI backend for the shift optimizer frontend.
Run with: uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.forecast_router import router

# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title="Shift Optimizer API",
    description="Optimize weekly driver schedules using CP-SAT solver",
    version="4.0",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev
        "http://localhost:3000",   # React dev
        "http://localhost:4173",   # Vite preview
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include router
app.include_router(router)


# =============================================================================
# ROOT
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Shift Optimizer API",
        "version": "4.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


# =============================================================================
# STARTUP
# =============================================================================

@app.on_event("startup")
async def startup():
    """Startup event."""
    print("=" * 60)
    print("SHIFT OPTIMIZER API v4.0")
    print("=" * 60)
    print("Endpoints:")
    print("  GET  /api/v1/health")
    print("  GET  /api/v1/constraints")
    print("  POST /api/v1/schedule")
    print("=" * 60)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
