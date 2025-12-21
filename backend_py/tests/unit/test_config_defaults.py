"""
Test: Default Configuration Values
===================================
Ensures critical defaults don't drift without intentional change.
"""
import pytest


def test_cap_quota_2er_default_is_030():
    """
    Safety-net: cap_quota_2er must default to 0.30 (30% reservation).
    
    This test prevents accidental regressions where the 2-tour block
    quota drops back to 0 (causing starvation).
    """
    from src.services.forecast_solver_v4 import ConfigV4
    
    config = ConfigV4()
    
    assert config.cap_quota_2er == 0.30, (
        f"cap_quota_2er default drifted! Expected 0.30, got {config.cap_quota_2er}. "
        "This value was validated in Stage 1 canary (170 runs, 0% infeasible, no starvation). "
        "If you need to change it, update this test and document the reason."
    )


def test_smart_block_builder_default_quota():
    """
    Verify build_weekly_blocks_smart uses 0.30 as default cap_quota_2er.
    """
    import inspect
    from src.services.smart_block_builder import build_weekly_blocks_smart
    
    sig = inspect.signature(build_weekly_blocks_smart)
    cap_quota_param = sig.parameters.get("cap_quota_2er")
    
    assert cap_quota_param is not None, "cap_quota_2er parameter not found"
    assert cap_quota_param.default == 0.30, (
        f"build_weekly_blocks_smart cap_quota_2er default drifted! "
        f"Expected 0.30, got {cap_quota_param.default}"
    )


def test_readyz_includes_cap_quota():
    """
    Ensure /readyz endpoint exposes cap_quota_2er for operational visibility.
    """
    from fastapi.testclient import TestClient
    from src.main import app
    
    client = TestClient(app)
    response = client.get("/api/v1/readyz")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "config" in data, "/readyz should include config block"
    assert "cap_quota_2er" in data["config"], "/readyz should include cap_quota_2er"
    assert data["config"]["cap_quota_2er"] == 0.30, (
        f"cap_quota_2er in /readyz is {data['config']['cap_quota_2er']}, expected 0.30"
    )
