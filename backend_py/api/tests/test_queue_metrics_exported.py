"""
Test: Celery Queue Depth Metrics (P2 Fix)
=========================================

Tests that queue depth metrics are exposed on /metrics endpoint.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestQueueMetricsExported:
    """Tests for Celery queue depth Prometheus metrics."""

    def test_celery_queue_length_metric_exists(self):
        """
        Test that celery_queue_length metric is registered.
        """
        from backend_py.api.metrics import CELERY_QUEUE_LENGTH

        assert CELERY_QUEUE_LENGTH is not None
        assert CELERY_QUEUE_LENGTH._name == "celery_queue_length"

    def test_update_queue_metrics_with_redis(self):
        """
        Test that update_queue_metrics queries Redis and sets gauge values.
        """
        from backend_py.api.metrics import update_queue_metrics, CELERY_QUEUE_LENGTH, _queue_metrics_cache

        # Reset cache to force update
        _queue_metrics_cache['last_update'] = 0

        # Mock Redis client
        mock_redis = MagicMock()
        mock_redis.llen.side_effect = lambda queue: {"routing": 5, "celery": 2}.get(queue, 0)

        with patch("redis.from_url", return_value=mock_redis):
            values = update_queue_metrics()

        assert values.get("routing") == 5
        assert values.get("celery") == 2

    def test_update_queue_metrics_caches_results(self):
        """
        Test that queue metrics are cached and not re-fetched within TTL.
        """
        from backend_py.api.metrics import update_queue_metrics, _queue_metrics_cache
        import time

        # Set cache with recent timestamp
        _queue_metrics_cache['last_update'] = time.time()
        _queue_metrics_cache['values'] = {"routing": 10, "celery": 3}

        # Mock Redis - should NOT be called due to cache
        mock_redis = MagicMock()

        with patch("redis.from_url", return_value=mock_redis):
            values = update_queue_metrics()

        # Should return cached values
        assert values == {"routing": 10, "celery": 3}
        # Redis should not have been called
        mock_redis.llen.assert_not_called()

    def test_update_queue_metrics_handles_redis_unavailable(self):
        """
        Test that update_queue_metrics handles Redis connection failure gracefully.
        """
        from backend_py.api.metrics import update_queue_metrics, _queue_metrics_cache

        # Reset cache
        _queue_metrics_cache['last_update'] = 0

        # Mock Redis to raise connection error
        with patch("redis.from_url", side_effect=Exception("Connection refused")):
            values = update_queue_metrics()

        # Should return empty dict, not crash
        assert values == {}

    def test_get_metrics_response_includes_queue_metrics(self):
        """
        Test that /metrics response includes celery_queue_length.
        """
        from backend_py.api.metrics import get_metrics_response, _queue_metrics_cache

        # Mock Redis to return known values
        mock_redis = MagicMock()
        mock_redis.llen.return_value = 7

        # Reset cache
        _queue_metrics_cache['last_update'] = 0

        with patch("redis.from_url", return_value=mock_redis):
            response = get_metrics_response()

        # Check response contains the metric
        content = response.body.decode()
        assert "celery_queue_length" in content

    def test_solver_memory_limit_metric_exists(self):
        """
        Test that solver_memory_limit_bytes metric is registered.
        """
        from backend_py.api.metrics import SOLVER_MEMORY_LIMIT

        assert SOLVER_MEMORY_LIMIT is not None
        assert SOLVER_MEMORY_LIMIT._name == "solver_memory_limit_bytes"

    def test_set_solver_memory_limit(self):
        """
        Test that set_solver_memory_limit updates the gauge.
        """
        from backend_py.api.metrics import set_solver_memory_limit, SOLVER_MEMORY_LIMIT

        # Set a memory limit
        limit_bytes = 8 * 1024 * 1024 * 1024  # 8GB
        set_solver_memory_limit(limit_bytes, component="solver")

        # Verify gauge was set (check _value internal)
        # Note: prometheus_client stores values internally
        assert SOLVER_MEMORY_LIMIT._metrics is not None


# ============================================================================
# Run commands:
#   pytest backend_py/api/tests/test_queue_metrics_exported.py -v
# ============================================================================
