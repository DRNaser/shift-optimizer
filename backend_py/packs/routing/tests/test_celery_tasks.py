# =============================================================================
# SOLVEREIGN Routing Pack - Celery Tasks Test
# =============================================================================
# Tests Celery task structure and imports (without requiring Redis).
#
# Run with: python packs/routing/tests/test_celery_tasks.py
# =============================================================================

import sys
sys.path.insert(0, ".")

import unittest
from unittest.mock import patch, MagicMock


class TestCeleryTasksStructure(unittest.TestCase):
    """Test Celery task structure and configuration."""

    def test_celery_app_import(self):
        """Test that Celery app can be imported."""
        from packs.routing.jobs.celery_app import celery_app

        self.assertIsNotNone(celery_app)
        self.assertEqual(celery_app.main, "routing")

    def test_celery_app_config(self):
        """Test Celery app configuration."""
        from packs.routing.jobs.celery_app import celery_app

        # Check important settings
        self.assertEqual(celery_app.conf.task_serializer, "json")
        self.assertEqual(celery_app.conf.timezone, "Europe/Berlin")
        self.assertTrue(celery_app.conf.enable_utc)
        self.assertEqual(celery_app.conf.task_time_limit, 600)
        self.assertEqual(celery_app.conf.worker_prefetch_multiplier, 1)

    def test_task_imports(self):
        """Test that tasks can be imported."""
        from packs.routing.jobs.tasks import solve_routing_scenario, repair_route

        self.assertIsNotNone(solve_routing_scenario)
        self.assertIsNotNone(repair_route)

    def test_task_names(self):
        """Test that tasks have correct names."""
        from packs.routing.jobs.tasks import solve_routing_scenario, repair_route

        self.assertEqual(solve_routing_scenario.name, "routing.solve_scenario")
        self.assertEqual(repair_route.name, "routing.repair_route")

    def test_solve_task_direct_call(self):
        """Test solve task can be called directly (without Celery)."""
        from packs.routing.jobs.tasks import solve_routing_scenario

        # Call the underlying function directly (bypass Celery)
        result = solve_routing_scenario.run(
            scenario_id="test-scenario-123",
            config={
                "time_limit_seconds": 10,
                "seed": 42,
            },
            tenant_id=1
        )

        self.assertIsNotNone(result)
        self.assertIn("status", result)
        self.assertIn("scenario_id", result)
        self.assertEqual(result["scenario_id"], "test-scenario-123")

    def test_repair_task_direct_call(self):
        """Test repair task can be called directly (without Celery)."""
        from packs.routing.jobs.tasks import repair_route

        # Call the underlying function directly (bypass Celery)
        result = repair_route.run(
            plan_id="test-plan-456",
            event={"type": "NO_SHOW", "affected_stop_ids": ["STOP_01"]},
            freeze_scope={"locked_stop_ids": []},
            tenant_id=1
        )

        self.assertIsNotNone(result)
        self.assertIn("status", result)
        self.assertIn("old_plan_id", result)
        self.assertEqual(result["old_plan_id"], "test-plan-456")

    def test_package_exports(self):
        """Test that package __init__ exports correctly."""
        from packs.routing.jobs import celery_app, solve_routing_scenario, repair_route

        self.assertIsNotNone(celery_app)
        self.assertIsNotNone(solve_routing_scenario)
        self.assertIsNotNone(repair_route)


class TestCeleryTaskRouting(unittest.TestCase):
    """Test Celery task routing configuration."""

    def test_task_queue_routing(self):
        """Test that tasks are routed to correct queues."""
        from packs.routing.jobs.celery_app import celery_app

        routes = celery_app.conf.task_routes

        self.assertIn("packs.routing.jobs.tasks.solve_routing_scenario", routes)
        self.assertIn("packs.routing.jobs.tasks.repair_route", routes)

        self.assertEqual(
            routes["packs.routing.jobs.tasks.solve_routing_scenario"]["queue"],
            "routing"
        )
        self.assertEqual(
            routes["packs.routing.jobs.tasks.repair_route"]["queue"],
            "routing"
        )


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Celery Tasks Test")
    print("=" * 70)
    print()

    # Run tests
    unittest.main(verbosity=2)
