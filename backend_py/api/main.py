"""
SOLVEREIGN V3.7 API - Main Application (UNIFIED ENTERPRISE API)
================================================================

FastAPI application with:
- JWT authentication (RS256) with RBAC
- Security headers (CSP, HSTS, etc.)
- Rate limiting (per-tenant, per-user, per-IP)
- Tenant isolation with RLS
- PII encryption (AES-256-GCM)
- Security audit logging with hash chain
- Prometheus metrics
- Structured logging
- Idempotency support

V3.7 AUTH SEPARATION (Wien W02):
================================
Platform Endpoints (Session Auth):
- /api/v1/platform/*      Platform admin operations (Cookie + CSRF)
- /api/v1/service-status  Service health (optional session)

Pack Endpoints (Tenant HMAC Auth):
- /api/v1/routing/*       Routing pack (API Key + HMAC)
- /api/v1/roster/*        Roster pack (API Key + HMAC)

Kernel Endpoints (API Key):
- /api/v1/forecasts/*     Forecast ingest (X-API-Key)
- /api/v1/plans/*         Plan management (X-API-Key)
- /api/v1/runs/*          Async runs (X-API-Key)

CRITICAL: No endpoint accepts both auth methods!

Endpoints:
- /health/*           Health check and readiness (NO AUTH)
- /api/v1/platform/*  Platform admin (SESSION AUTH)
- /api/v1/routing/*   Routing pack (HMAC AUTH)
- /api/v1/roster/*    Roster pack (HMAC AUTH)
- /api/v1/forecasts/* Forecast ingest (API KEY)
- /api/v1/plans/*     Solve, audit, lock, export (API KEY)
- /api/v1/runs/*      Async optimization with SSE (API KEY)
- /metrics            Prometheus metrics (NO AUTH)

This is the UNIFIED Enterprise API replacing the legacy src/main.py.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .logging_config import setup_logging, get_logger
from .database import DatabaseManager

# Setup logging first
setup_logging()
logger = get_logger(__name__)


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events:
    - Database connection pool initialization
    - Metrics setup
    - Cleanup on shutdown
    """
    logger.info(
        "starting_application",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        }
    )

    # Startup: Initialize database pool
    db_manager = DatabaseManager()
    await db_manager.initialize()
    app.state.db = db_manager

    logger.info("database_pool_initialized")

    # Initialize PolicyService (kernel service for pack configuration)
    from .services.policy_service import init_policy_service
    policy_service = init_policy_service(db_manager.pool)
    app.state.policy_service = policy_service

    logger.info("policy_service_initialized")

    yield

    # Shutdown: Close database connections
    await db_manager.close()
    logger.info("application_shutdown_complete")


# =============================================================================
# APPLICATION FACTORY
# =============================================================================

def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Returns:
        Configured FastAPI instance
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production-ready shift scheduling optimization API",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # Configure middleware
    configure_middleware(app)

    # Register routers
    register_routers(app)

    # Register exception handlers
    register_exception_handlers(app)

    return app


# =============================================================================
# MIDDLEWARE CONFIGURATION
# =============================================================================

def configure_middleware(app: FastAPI) -> None:
    """
    Configure all middleware.

    CRITICAL: Order matters! Execution is LIFO (last added = first executed).
    Adding order (bottom-up) → Execution order (top-down):

    1. SecurityHeaders (outermost - always runs)
    2. CORS (before auth to handle preflight)
    3. AuthSeparation (V3.7 - enforces platform vs pack auth)
    4. RequestContext (sets request_id, timing)
    5. Auth (per-route via dependencies)
    6. RateLimit (AFTER auth - can use tenant_id/user_id)
    7. Router handlers (innermost)
    """
    from .security.headers import SecurityHeadersMiddleware
    from .security.rate_limit import RateLimitMiddleware

    # NOTE: FastAPI middleware is LIFO - last added executes FIRST
    # So we add in REVERSE order of desired execution

    # 6. Rate limiting - runs AFTER auth (has access to tenant_id/user_id)
    app.add_middleware(RateLimitMiddleware)

    # 5. Auth middleware will be applied via dependencies (per-route)
    # This allows public endpoints (/health, /metrics) to skip auth

    # 4. RequestContext is added below as @app.middleware("http")

    # 3. Auth separation enforcement middleware (V3.7)
    # Blocks mismatched auth methods at middleware level
    @app.middleware("http")
    async def enforce_auth_separation(request: Request, call_next):
        """
        V3.7 AUTH SEPARATION ENFORCEMENT (Hardened)

        Rejects requests that use wrong auth method for endpoint type:
        - Platform endpoints (/api/v1/platform/*): REJECT API-Key, HMAC headers
        - Pack endpoints (/api/v1/routing/*, /api/v1/roster/*): REJECT session cookies

        SECURITY HARDENING (Blindspot fixes):
        - Exact prefix matching with boundary check (not just startswith)
        - Normalized path (no encoded chars, no trailing slash abuse)
        - /api/v1/platformXYZ does NOT match as platform endpoint
        """
        from urllib.parse import unquote

        # Get raw path and normalize
        raw_path = request.url.path

        # SECURITY: Decode URL-encoded chars to prevent bypass via %2F etc.
        # This catches attempts like /api/v1/platform%2Fbypass
        decoded_path = unquote(raw_path)

        # SECURITY: Normalize trailing slashes for consistent matching
        # /api/v1/platform/ and /api/v1/platform should both match
        path = decoded_path.rstrip("/") if decoded_path != "/" else decoded_path

        # Skip for public endpoints
        if path.startswith("/health") or path == "/metrics" or path == "":
            return await call_next(request)

        def is_prefix_match(check_path: str, prefix: str) -> bool:
            """
            SECURITY: Exact prefix match with boundary check.

            /api/v1/platform matches /api/v1/platform and /api/v1/platform/foo
            /api/v1/platform does NOT match /api/v1/platformXYZ

            Returns True if check_path equals prefix OR starts with prefix + "/"
            """
            return check_path == prefix or check_path.startswith(prefix + "/")

        # Platform endpoints: reject tenant auth
        if is_prefix_match(path, "/api/v1/platform"):
            tenant_headers = ["X-API-Key", "X-SV-Signature", "X-SV-Nonce"]
            found_tenant_auth = [h for h in tenant_headers if request.headers.get(h)]
            if found_tenant_auth:
                logger.warning(
                    "auth_separation_violation_platform",
                    extra={
                        "path": path,
                        "raw_path": raw_path,
                        "found_headers": found_tenant_auth,
                        "source_ip": request.client.host if request.client else "unknown"
                    }
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "auth_method_mismatch",
                        "message": "Platform endpoints require session auth. API Key / HMAC not accepted.",
                        "rejected_headers": found_tenant_auth
                    }
                )

        # Pack endpoints: reject session auth
        pack_prefixes = ["/api/v1/routing", "/api/v1/roster"]
        if any(is_prefix_match(path, prefix) for prefix in pack_prefixes):
            session_cookie = request.cookies.get("sv_session")
            csrf_header = request.headers.get("X-CSRF-Token")
            if session_cookie or csrf_header:
                logger.warning(
                    "auth_separation_violation_pack",
                    extra={
                        "path": path,
                        "raw_path": raw_path,
                        "has_session": bool(session_cookie),
                        "has_csrf": bool(csrf_header),
                        "source_ip": request.client.host if request.client else "unknown"
                    }
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "auth_method_mismatch",
                        "message": "Pack endpoints require HMAC auth. Session cookies not accepted.",
                    }
                )

        return await call_next(request)

    # 2. CORS - must run before auth to handle OPTIONS preflight
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # 1. Security headers - outermost, always runs
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)

    # Request ID, timing, and metrics middleware
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        """Add request ID, timing, and record metrics for all requests."""
        import uuid
        from .metrics import record_http_request

        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.perf_counter()

        # Store in request state
        request.state.request_id = request_id
        request.state.start_time = start_time

        # Process request
        response: Response = await call_next(request)

        # Calculate duration
        duration_seconds = time.perf_counter() - start_time
        duration_ms = duration_seconds * 1000

        # Add response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"

        # Record Prometheus metrics (skip /metrics endpoint itself)
        if request.url.path != "/metrics":
            record_http_request(
                method=request.method,
                endpoint=request.url.path,
                status_code=response.status_code,
                duration_seconds=duration_seconds
            )

        # Log request completion
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            }
        )

        return response


# =============================================================================
# ROUTER REGISTRATION
# =============================================================================

def register_routers(app: FastAPI) -> None:
    """Register all API routers."""

    # Import routers here to avoid circular imports
    from .routers import (
        health, forecasts, plans, tenants,
        simulations, runs, repair, config,
        core_tenant, platform, platform_orgs, service_status,
        policies, dispatcher_platform
    )

    # Health check (no auth required)
    app.include_router(
        health.router,
        prefix="/health",
        tags=["Health"],
    )

    # API v1 routes
    api_prefix = "/api/v1"

    # Legacy tenant management (integer ID, X-API-Key)
    app.include_router(
        tenants.router,
        prefix=f"{api_prefix}/tenants",
        tags=["Tenants (Legacy)"],
    )

    # Core tenant self-service (UUID, X-Tenant-Code)
    app.include_router(
        core_tenant.router,
        prefix=f"{api_prefix}/tenant",
        tags=["Tenant"],
    )

    # Platform admin operations (X-Platform-Admin)
    app.include_router(
        platform.router,
        prefix=f"{api_prefix}/platform",
        tags=["Platform Admin"],
    )

    # Platform organization management (requires internal signature)
    app.include_router(
        platform_orgs.router,
        prefix=f"{api_prefix}/platform",
        tags=["Platform Organizations"],
    )

    # Service status and escalation management
    app.include_router(
        service_status.router,
        prefix=f"{api_prefix}",
        tags=["Service Status"],
    )

    # Dispatcher cockpit (platform session auth + tenant context headers)
    app.include_router(
        dispatcher_platform.router,
        prefix=f"{api_prefix}/platform/dispatcher",
        tags=["Dispatcher Cockpit"],
    )

    app.include_router(
        forecasts.router,
        prefix=f"{api_prefix}/forecasts",
        tags=["Forecasts"],
    )

    app.include_router(
        plans.router,
        prefix=f"{api_prefix}/plans",
        tags=["Plans"],
    )

    app.include_router(
        simulations.router,
        prefix=f"{api_prefix}/simulations",
        tags=["Simulations"],
    )

    # NEW: Runs router for async optimization with SSE streaming
    app.include_router(
        runs.router,
        prefix=f"{api_prefix}/runs",
        tags=["Runs"],
    )

    # NEW: Repair router for driver absence handling
    # Note: Nested under /plans for REST semantics
    app.include_router(
        repair.router,
        prefix=f"{api_prefix}/plans",
        tags=["Repair"],
    )

    # NEW: Config router for schema and validation
    app.include_router(
        config.router,
        prefix=f"{api_prefix}/config",
        tags=["Config"],
    )

    # Policy profiles management (Kernel service, see ADR-002)
    app.include_router(
        policies.router,
        prefix=f"{api_prefix}/policies",
        tags=["Policies"],
    )

    # =========================================================================
    # PACK ROUTERS (Domain-specific, see ADR-001)
    # =========================================================================

    # Roster Pack (Phase 1: wrapper around kernel routers)
    try:
        from ..packs.roster.api import router as roster_router
        app.include_router(
            roster_router,
            prefix=f"{api_prefix}/roster",
            tags=["Roster Pack"],
        )
        logger.info("roster_pack_router_registered", extra={"prefix": f"{api_prefix}/roster"})
    except ImportError as e:
        logger.warning("roster_pack_not_available", extra={"error": str(e)})

    # Routing Pack (already exists in packs/)
    try:
        from ..packs.routing.api.routers import scenarios, routes
        app.include_router(
            scenarios.router,
            prefix=f"{api_prefix}/routing/scenarios",
            tags=["Routing Scenarios"],
        )
        app.include_router(
            routes.router,
            prefix=f"{api_prefix}/routing",
            tags=["Routing Routes"],
        )
        logger.info("routing_pack_router_registered", extra={"prefix": f"{api_prefix}/routing"})
    except ImportError as e:
        logger.warning("routing_pack_not_available", extra={"error": str(e)})

    # Prometheus metrics endpoint (always registered)
    from .metrics import get_metrics_response

    @app.get("/metrics", tags=["Monitoring"], include_in_schema=False)
    async def metrics_endpoint():
        """
        Prometheus metrics endpoint.

        Returns metrics in Prometheus text format:
        - solve_duration_seconds (Histogram)
        - solve_failures_total (Counter)
        - audit_failures_total (Counter)
        - http_requests_total (Counter)
        - http_request_duration_seconds (Histogram)
        - solvereign_build_info (Info)
        """
        return get_metrics_response()

    logger.info("metrics_endpoint_registered", extra={"path": "/metrics"})


# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================

def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers."""

    from .exceptions import (
        SolvereIgnError,
        TenantNotFoundError,
        ForecastNotFoundError,
        PlanNotFoundError,
        ConcurrencyError,
        IdempotencyConflictError,
        ValidationError,
    )
    from .security.rate_limit import RateLimitExceeded

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded", "message": str(exc)},
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(TenantNotFoundError)
    async def tenant_not_found_handler(request: Request, exc: TenantNotFoundError):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": str(exc)},
        )

    @app.exception_handler(ForecastNotFoundError)
    async def forecast_not_found_handler(request: Request, exc: ForecastNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": str(exc)},
        )

    @app.exception_handler(PlanNotFoundError)
    async def plan_not_found_handler(request: Request, exc: PlanNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": str(exc)},
        )

    @app.exception_handler(ConcurrencyError)
    async def concurrency_handler(request: Request, exc: ConcurrencyError):
        return JSONResponse(
            status_code=423,  # Locked
            content={"error": "locked", "message": str(exc)},
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(request: Request, exc: IdempotencyConflictError):
        return JSONResponse(
            status_code=409,
            content={"error": "conflict", "message": str(exc)},
        )

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": str(exc), "details": exc.details},
        )

    @app.exception_handler(SolvereIgnError)
    async def generic_error_handler(request: Request, exc: SolvereIgnError):
        logger.error(
            "unhandled_application_error",
            extra={"error": str(exc), "type": type(exc).__name__}
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "An unexpected error occurred"},
        )


# =============================================================================
# APPLICATION INSTANCE
# =============================================================================

app = create_app()


# =============================================================================
# ROOT ENDPOINT
# =============================================================================

@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint with API info."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if not settings.is_production else None,
        "health": "/health",
    }


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
        log_level=settings.log_level.lower(),
    )
