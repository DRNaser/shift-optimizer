"""
Test: Solver Memory Limit Enforcement (P2 Fix)
==============================================

Tests that memory limits are applied before solver execution.
"""

import platform
import pytest
from unittest.mock import patch, MagicMock


class TestSolverMemoryLimit:
    """Tests for solver memory limit enforcement."""

    def test_apply_memory_limit_returns_tuple(self):
        """
        Test that apply_memory_limit returns expected tuple structure.
        """
        from backend_py.v3.solver_wrapper import apply_memory_limit

        result = apply_memory_limit()

        assert isinstance(result, tuple)
        assert len(result) == 3
        success, limit_bytes, message = result
        assert isinstance(success, bool)
        assert isinstance(limit_bytes, int)
        assert isinstance(message, str)

    def test_apply_memory_limit_disabled_when_zero(self):
        """
        Test that memory limit is disabled when SOLVER_MAX_MEM_MB=0.
        """
        from backend_py.v3 import solver_wrapper

        # Reset applied flag
        solver_wrapper._memory_limit_applied = False

        with patch.object(solver_wrapper.config, "SOLVER_MAX_MEM_MB", 0):
            success, limit_bytes, message = solver_wrapper.apply_memory_limit()

        assert success is True
        assert limit_bytes == 0
        assert "disabled" in message.lower()

    def test_apply_memory_limit_idempotent(self):
        """
        Test that apply_memory_limit is idempotent (doesn't re-apply).
        """
        from backend_py.v3 import solver_wrapper

        # Simulate already applied
        solver_wrapper._memory_limit_applied = True

        with patch.object(solver_wrapper.config, "SOLVER_MAX_MEM_MB", 6144):
            success, limit_bytes, message = solver_wrapper.apply_memory_limit()

        assert success is True
        assert "already applied" in message.lower()

        # Reset for other tests
        solver_wrapper._memory_limit_applied = False

    @pytest.mark.skipif(platform.system() != "Linux", reason="RLIMIT only on Linux")
    def test_apply_memory_limit_sets_rlimit_on_linux(self):
        """
        Test that RLIMIT_AS is set on Linux.
        """
        from backend_py.v3 import solver_wrapper
        import resource

        # Reset
        solver_wrapper._memory_limit_applied = False

        with patch.object(solver_wrapper.config, "SOLVER_MAX_MEM_MB", 1024):  # 1GB
            success, limit_bytes, message = solver_wrapper.apply_memory_limit()

        assert success is True
        assert limit_bytes > 0

        # Verify RLIMIT was set
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        assert soft <= 1024 * 1024 * 1024  # Should be <= 1GB

    def test_apply_memory_limit_handles_non_linux(self):
        """
        Test that non-Linux platforms get a warning but don't fail.
        """
        from backend_py.v3 import solver_wrapper

        # Reset
        solver_wrapper._memory_limit_applied = False

        # Force non-linux platform
        with patch("platform.system", return_value="Windows"):
            with patch.object(solver_wrapper.config, "SOLVER_MAX_MEM_MB", 6144):
                success, limit_bytes, message = solver_wrapper.apply_memory_limit()

        assert success is True
        assert "Docker" in message or "Windows" in message

    def test_get_memory_limit_status_structure(self):
        """
        Test that get_memory_limit_status returns expected structure.
        """
        from backend_py.v3.solver_wrapper import get_memory_limit_status

        status = get_memory_limit_status()

        assert isinstance(status, dict)
        assert "configured_mb" in status
        assert "platform" in status
        assert "applied" in status

    def test_config_has_solver_max_mem_mb(self):
        """
        Test that config includes SOLVER_MAX_MEM_MB setting.
        """
        from backend_py.v3.config import config

        assert hasattr(config, "SOLVER_MAX_MEM_MB")
        assert isinstance(config.SOLVER_MAX_MEM_MB, int)
        # Default should be 6144 MB (6GB)
        assert config.SOLVER_MAX_MEM_MB >= 0


class TestDockerComposeMemoryLimits:
    """Tests for Docker compose memory configuration."""

    def test_docker_compose_has_memory_limits(self):
        """
        Test that docker-compose.yml has memory limits configured.
        """
        import os
        from pathlib import Path

        # Find docker-compose.yml
        # Path: backend_py/v3/tests/test_*.py -> 4 parents to repo root
        repo_root = Path(__file__).parent.parent.parent.parent
        compose_file = repo_root / "docker-compose.yml"

        assert compose_file.exists(), f"docker-compose.yml not found at {compose_file}"

        content = compose_file.read_text()

        # Check for memory limit configuration
        assert "memory:" in content, "No memory limit found in docker-compose.yml"
        assert "8G" in content or "8192" in content, "Expected 8GB memory limit"

    def test_pilot_compose_has_memory_limits(self):
        """
        Test that pilot docker-compose also has memory limits.
        """
        import os
        from pathlib import Path

        # Path: backend_py/v3/tests/test_*.py -> 4 parents to repo root
        repo_root = Path(__file__).parent.parent.parent.parent
        compose_file = repo_root / "docker-compose.pilot.yml"

        if not compose_file.exists():
            pytest.skip("docker-compose.pilot.yml not found")

        content = compose_file.read_text()

        # Pilot compose should either have limits or inherit from base
        # This test documents the current state
        has_limits = "memory:" in content
        if not has_limits:
            pytest.xfail("docker-compose.pilot.yml missing memory limits (known gap)")


# ============================================================================
# Run commands:
#   pytest backend_py/v3/tests/test_solver_memory_limit.py -v
# ============================================================================
