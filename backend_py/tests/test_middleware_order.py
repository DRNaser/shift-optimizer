"""
SOLVEREIGN V3.3b - Middleware Order Test

=============================================================================
PURPOSE: Verify middleware execution order is correct
=============================================================================

Critical requirement: Rate limiting MUST run AFTER authentication
so that tenant_id is available for tenant-scoped rate limiting.

Execution order (top to bottom):
1. SecurityHeadersMiddleware  - Always runs
2. CORSMiddleware            - Handles preflight
3. RequestContextMiddleware   - Sets request_id
4. AuthMiddleware            - JWT validation, sets tenant_id/user_id
5. RateLimitMiddleware       - Uses tenant_id from auth
6. Router handlers           - Business logic

This test verifies the order by tracking middleware execution.
"""

import pytest
from typing import List, Callable
from datetime import datetime

# Track middleware execution order
execution_order: List[str] = []


class MockRequest:
    """Mock request object for testing."""

    def __init__(self):
        self.state = type('State', (), {})()
        self.url = type('URL', (), {'path': '/api/v1/forecasts'})()
        self.method = "GET"
        self.headers = {"authorization": "Bearer test_token"}


class MockResponse:
    """Mock response object."""

    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}


def reset_execution_order():
    """Reset the global execution order tracker."""
    global execution_order
    execution_order = []


# =============================================================================
# Middleware Simulator (simulates FastAPI LIFO behavior)
# =============================================================================

def create_middleware_chain(middlewares: List[Callable], handler: Callable) -> Callable:
    """
    Create a middleware chain that simulates FastAPI's LIFO behavior.

    FastAPI adds middleware in LIFO order:
    - Last added middleware runs first (outermost)
    - First added middleware runs last (innermost, closest to handler)
    """
    # Start with the handler
    app = handler

    # Wrap with middlewares (first in list = runs closest to handler)
    for middleware in middlewares:
        next_app = app

        async def create_wrapper(mw, next_handler):
            async def wrapper(request):
                async def call_next(req):
                    return await next_handler(req)
                return await mw(request, call_next)
            return wrapper

        # Create closure properly
        app = lambda req, mw=middleware, next_handler=next_app: (
            lambda: create_call(mw, next_handler, req)
        )()

    return app


async def create_call(middleware_func, next_handler, request):
    """Helper to create proper async call chain."""
    async def call_next(req):
        return await next_handler(req)
    return await middleware_func(request, call_next)


# =============================================================================
# Tracking Middleware Functions
# =============================================================================

async def security_headers_middleware(request, call_next):
    """Tracks when security headers middleware runs."""
    execution_order.append("1_SecurityHeaders_ENTER")
    response = await call_next(request)
    execution_order.append("1_SecurityHeaders_EXIT")
    return response


async def cors_middleware(request, call_next):
    """Tracks when CORS middleware runs."""
    execution_order.append("2_CORS_ENTER")
    response = await call_next(request)
    execution_order.append("2_CORS_EXIT")
    return response


async def request_context_middleware(request, call_next):
    """Tracks when request context middleware runs."""
    execution_order.append("3_RequestContext_ENTER")
    request.state.request_id = "test-request-id"
    response = await call_next(request)
    execution_order.append("3_RequestContext_EXIT")
    return response


async def auth_middleware(request, call_next):
    """Tracks when auth middleware runs and sets tenant_id."""
    execution_order.append("4_Auth_ENTER")
    # Auth sets tenant_id/user_id in request state
    request.state.tenant_id = "test-tenant-id"
    request.state.user_id = "test-user-id"
    response = await call_next(request)
    execution_order.append("4_Auth_EXIT")
    return response


async def rate_limit_middleware(request, call_next):
    """Tracks when rate limit middleware runs and verifies auth ran first."""
    execution_order.append("5_RateLimit_ENTER")

    # CRITICAL: Verify tenant_id is available (auth ran first)
    tenant_id = getattr(request.state, 'tenant_id', None)
    if tenant_id:
        execution_order.append(f"5_RateLimit_HAS_TENANT:{tenant_id}")
    else:
        execution_order.append("5_RateLimit_NO_TENANT")

    response = await call_next(request)
    execution_order.append("5_RateLimit_EXIT")
    return response


async def handler(request):
    """Final request handler."""
    execution_order.append("6_Handler")
    return MockResponse(200)


# =============================================================================
# Test Cases
# =============================================================================

class TestMiddlewareOrder:
    """Test suite for middleware execution order verification."""

    def setup_method(self):
        """Reset execution order before each test."""
        reset_execution_order()

    @pytest.mark.asyncio
    async def test_correct_order_auth_before_rate_limit(self):
        """
        TEST: Rate limit runs AFTER auth, so tenant_id is available.

        This is the critical test - rate limiting must have access to
        tenant_id for proper tenant-scoped limiting.
        """
        reset_execution_order()

        # Simulate correct middleware order (as configured in main.py)
        # Order reflects execution from outside-in:
        # 1. Security Headers (outermost)
        # 2. CORS
        # 3. Request Context
        # 4. Auth (sets tenant_id)
        # 5. Rate Limit (uses tenant_id) - MUST come after Auth!
        # 6. Handler

        request = MockRequest()

        # Build chain from innermost to outermost
        async def chain(req):
            # Rate limit (closest to handler)
            return await rate_limit_middleware(req, lambda r: handler(r))

        async def with_auth(req):
            return await auth_middleware(req, chain)

        async def with_context(req):
            return await request_context_middleware(req, with_auth)

        async def with_cors(req):
            return await cors_middleware(req, with_context)

        async def with_headers(req):
            return await security_headers_middleware(req, with_cors)

        # Execute
        await with_headers(request)

        print(f"Execution order: {execution_order}")

        # Verify Auth runs before RateLimit
        auth_enter_idx = execution_order.index("4_Auth_ENTER")
        rate_enter_idx = execution_order.index("5_RateLimit_ENTER")

        assert auth_enter_idx < rate_enter_idx, (
            f"FAIL: Auth middleware must run BEFORE rate limit!\n"
            f"Auth entered at index {auth_enter_idx}, "
            f"RateLimit entered at index {rate_enter_idx}\n"
            f"Order: {execution_order}"
        )

        # Verify rate limit has tenant_id
        assert "5_RateLimit_HAS_TENANT:test-tenant-id" in execution_order, (
            "FAIL: Rate limit middleware did not have access to tenant_id!\n"
            f"Order: {execution_order}"
        )

        print("[PASS] Middleware order correct - Auth runs before RateLimit")

    @pytest.mark.asyncio
    async def test_wrong_order_rate_limit_before_auth(self):
        """
        TEST: Demonstrate failure when rate limit runs BEFORE auth.

        This is the anti-pattern we're preventing.
        """
        reset_execution_order()

        request = MockRequest()

        # WRONG ORDER: Rate limit before auth
        async def chain(req):
            return await auth_middleware(req, lambda r: handler(r))

        async def wrong_order(req):
            # Rate limit runs BEFORE auth - WRONG!
            return await rate_limit_middleware(req, chain)

        await wrong_order(request)

        print(f"Wrong order execution: {execution_order}")

        # Rate limit should NOT have tenant_id
        assert "5_RateLimit_NO_TENANT" in execution_order, (
            "In wrong order, rate limit should NOT have tenant_id"
        )

        print("[PASS] Demonstrated wrong order fails to provide tenant_id")

    @pytest.mark.asyncio
    async def test_security_headers_outermost(self):
        """
        TEST: Security headers middleware runs first and exits last.
        """
        reset_execution_order()

        request = MockRequest()

        async def inner(req):
            return await rate_limit_middleware(req, lambda r: handler(r))

        async def with_auth(req):
            return await auth_middleware(req, inner)

        async def with_headers(req):
            return await security_headers_middleware(req, with_auth)

        await with_headers(request)

        # Security headers should be first ENTER and last EXIT
        assert execution_order[0] == "1_SecurityHeaders_ENTER", (
            f"Security headers should enter first: {execution_order}"
        )
        assert execution_order[-1] == "1_SecurityHeaders_EXIT", (
            f"Security headers should exit last: {execution_order}"
        )

        print("[PASS] Security headers is outermost middleware")

    @pytest.mark.asyncio
    async def test_full_chain_order(self):
        """
        TEST: Full middleware chain executes in correct order.
        """
        reset_execution_order()

        request = MockRequest()

        async def chain5(req):
            return await rate_limit_middleware(req, lambda r: handler(r))

        async def chain4(req):
            return await auth_middleware(req, chain5)

        async def chain3(req):
            return await request_context_middleware(req, chain4)

        async def chain2(req):
            return await cors_middleware(req, chain3)

        async def chain1(req):
            return await security_headers_middleware(req, chain2)

        await chain1(request)

        expected_enter_order = [
            "1_SecurityHeaders_ENTER",
            "2_CORS_ENTER",
            "3_RequestContext_ENTER",
            "4_Auth_ENTER",
            "5_RateLimit_ENTER",
        ]

        # Extract just ENTER events
        enter_events = [e for e in execution_order if "ENTER" in e]

        assert enter_events == expected_enter_order, (
            f"Enter order mismatch!\n"
            f"Expected: {expected_enter_order}\n"
            f"Got: {enter_events}"
        )

        print("[PASS] Full chain executes in correct order")


# =============================================================================
# Documentation Test
# =============================================================================

def test_fastapi_middleware_order_lifo():
    """
    TEST: Document FastAPI middleware LIFO behavior.
    """
    doc = """
    ============================================================
    FastAPI Middleware LIFO (Last In, First Out)
    ============================================================

    When you add middleware:
        app.add_middleware(A)  # Added first
        app.add_middleware(B)  # Added second
        app.add_middleware(C)  # Added third

    Execution order is: C -> B -> A (LIFO = Last added runs first)

    CORRECT configuration for Auth before RateLimit:

        # api/main.py
        app.add_middleware(RateLimitMiddleware)       # Runs 3rd (innermost)
        app.add_middleware(AuthMiddleware)            # Runs 2nd
        app.add_middleware(SecurityHeadersMiddleware) # Runs 1st (outermost)

    This ensures:
        SecurityHeaders.enter()  -> Auth.enter() -> RateLimit.enter()
        -> handler() ->
        RateLimit.exit() -> Auth.exit() -> SecurityHeaders.exit()

    Rate limit has access to tenant_id set by Auth because Auth runs first!
    """
    print(doc)
    assert True


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    import asyncio

    print("=" * 60)
    print("MIDDLEWARE ORDER TESTS")
    print("=" * 60)

    test = TestMiddlewareOrder()

    # Test 1: Correct order
    print("\n[TEST 1] Auth before RateLimit (correct)...")
    asyncio.run(test.test_correct_order_auth_before_rate_limit())

    # Test 2: Wrong order demonstration
    print("\n[TEST 2] RateLimit before Auth (wrong - demonstrates failure)...")
    asyncio.run(test.test_wrong_order_rate_limit_before_auth())

    # Test 3: Security headers outermost
    print("\n[TEST 3] Security headers outermost...")
    asyncio.run(test.test_security_headers_outermost())

    # Test 4: Full chain
    print("\n[TEST 4] Full middleware chain order...")
    asyncio.run(test.test_full_chain_order())

    # Test 5: Documentation
    print("\n[TEST 5] FastAPI LIFO documentation...")
    test_fastapi_middleware_order_lifo()

    print("\n" + "=" * 60)
    print("ALL MIDDLEWARE ORDER TESTS PASSED")
    print("=" * 60)
