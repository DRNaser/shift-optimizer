"""
Roster Pack API

Exposes roster-specific endpoints under /api/v1/roster/*

Routers:
- forecasts: Forecast ingest and parsing
- plans: Solve, audit, lock, export
- simulations: What-if scenario analysis
- repair: Driver absence handling
- config: Pack configuration (tunable vs locked fields)
"""

from .routers import router

__all__ = ["router"]
