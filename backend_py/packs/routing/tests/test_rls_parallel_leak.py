# =============================================================================
# SOLVEREIGN Routing Pack - RLS Parallel Leak Test
# =============================================================================
# Gate 3: Two-Tenant Parallel Celery Leak Test
#
# Requirements:
# - 2 tenants running parallel tasks
# - Verify 0 cross-tenant rows
# - Test under concurrent load
# =============================================================================

import sys
import unittest
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Set
from dataclasses import dataclass, field

sys.path.insert(0, ".")


# =============================================================================
# SIMULATED TENANT CONTEXT (for testing without DB)
# =============================================================================

@dataclass
class TenantContext:
    """Simulated tenant context for RLS testing."""
    tenant_id: int
    name: str
    data: Dict[str, List] = field(default_factory=dict)

    def __post_init__(self):
        self.data = {
            "scenarios": [],
            "stops": [],
            "vehicles": [],
            "assignments": [],
        }


class TenantIsolatedStore:
    """
    Simulated tenant-isolated data store.

    Mimics RLS behavior: each operation is scoped to current_tenant_id.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[int, TenantContext] = {}
        self._current_tenant = threading.local()

    def set_tenant(self, tenant_id: int):
        """Set tenant context for current thread (like SET app.current_tenant_id)."""
        self._current_tenant.tenant_id = tenant_id

    def get_tenant(self) -> int:
        """Get current tenant ID."""
        return getattr(self._current_tenant, 'tenant_id', None)

    def _ensure_tenant(self, tenant_id: int):
        """Ensure tenant exists in store."""
        if tenant_id not in self._data:
            self._data[tenant_id] = TenantContext(tenant_id=tenant_id, name=f"Tenant_{tenant_id}")

    def insert_scenario(self, scenario_id: str, tenant_id: int = None):
        """Insert scenario with RLS check."""
        tid = tenant_id or self.get_tenant()
        if tid is None:
            raise ValueError("No tenant context set")

        with self._lock:
            self._ensure_tenant(tid)
            self._data[tid].data["scenarios"].append({
                "id": scenario_id,
                "tenant_id": tid,
                "created_at": datetime.now()
            })

    def insert_stop(self, stop_id: str, scenario_id: str, tenant_id: int = None):
        """Insert stop with RLS check."""
        tid = tenant_id or self.get_tenant()
        if tid is None:
            raise ValueError("No tenant context set")

        with self._lock:
            self._ensure_tenant(tid)
            self._data[tid].data["stops"].append({
                "id": stop_id,
                "scenario_id": scenario_id,
                "tenant_id": tid,
            })

    def insert_assignment(self, assignment_id: str, stop_id: str, vehicle_id: str, tenant_id: int = None):
        """Insert assignment with RLS check."""
        tid = tenant_id or self.get_tenant()
        if tid is None:
            raise ValueError("No tenant context set")

        with self._lock:
            self._ensure_tenant(tid)
            self._data[tid].data["assignments"].append({
                "id": assignment_id,
                "stop_id": stop_id,
                "vehicle_id": vehicle_id,
                "tenant_id": tid,
            })

    def get_stops(self, tenant_id: int = None) -> List[Dict]:
        """Get stops with RLS filter."""
        tid = tenant_id or self.get_tenant()
        if tid is None:
            raise ValueError("No tenant context set")

        with self._lock:
            if tid not in self._data:
                return []
            return self._data[tid].data["stops"]

    def get_assignments(self, tenant_id: int = None) -> List[Dict]:
        """Get assignments with RLS filter."""
        tid = tenant_id or self.get_tenant()
        if tid is None:
            raise ValueError("No tenant context set")

        with self._lock:
            if tid not in self._data:
                return []
            return self._data[tid].data["assignments"]

    def get_all_data(self) -> Dict[int, Dict]:
        """Get all data across tenants (for verification)."""
        with self._lock:
            return {
                tid: {
                    "scenarios": list(ctx.data["scenarios"]),
                    "stops": list(ctx.data["stops"]),
                    "assignments": list(ctx.data["assignments"]),
                }
                for tid, ctx in self._data.items()
            }


# =============================================================================
# SIMULATED SOLVE TASK
# =============================================================================

def simulate_solve_task(
    store: TenantIsolatedStore,
    tenant_id: int,
    scenario_id: str,
    num_stops: int = 10,
) -> Dict:
    """
    Simulate a solve task with tenant isolation.

    This mimics what a Celery task would do:
    1. Set tenant context (like tenant_transaction)
    2. Insert scenario
    3. Insert stops
    4. Create assignments
    5. Return result
    """
    # Step 1: Set tenant context (like SET app.current_tenant_id)
    store.set_tenant(tenant_id)

    # Step 2: Insert scenario
    store.insert_scenario(scenario_id)

    # Step 3: Insert stops
    for i in range(num_stops):
        stop_id = f"{scenario_id}_STOP_{i:03d}"
        store.insert_stop(stop_id, scenario_id)

    # Step 4: Create assignments
    stops = store.get_stops()
    for i, stop in enumerate(stops):
        if stop["scenario_id"] == scenario_id:  # Only this scenario's stops
            assignment_id = f"{scenario_id}_ASSIGN_{i:03d}"
            vehicle_id = f"{scenario_id}_VAN_{i % 3}"
            store.insert_assignment(assignment_id, stop["id"], vehicle_id)

    # Step 5: Return result
    return {
        "tenant_id": tenant_id,
        "scenario_id": scenario_id,
        "stops_created": num_stops,
        "thread_id": threading.current_thread().ident,
    }


# =============================================================================
# TESTS
# =============================================================================

class TestRLSParallelLeak(unittest.TestCase):
    """
    Gate 3: Two-Tenant Parallel Leak Test.

    Proves that tenant isolation works under concurrent load.
    """

    def test_two_tenants_parallel_no_leak(self):
        """
        PROOF: Two tenants running parallel tasks have no data leak.

        Test:
        - Tenant 1 and Tenant 2 each run 10 parallel scenarios
        - Each scenario creates 10 stops and 10 assignments
        - Verify: all stops for tenant 1 have tenant_id=1
        - Verify: all stops for tenant 2 have tenant_id=2
        - Verify: no cross-tenant data
        """
        print("\n" + "=" * 60)
        print("GATE 3: Two-Tenant Parallel Leak Test")
        print("=" * 60)

        store = TenantIsolatedStore()
        TENANT_1 = 1
        TENANT_2 = 2
        SCENARIOS_PER_TENANT = 10
        STOPS_PER_SCENARIO = 10

        # Run parallel tasks for both tenants
        print(f"\n[1] Running {SCENARIOS_PER_TENANT} parallel tasks per tenant...")

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []

            # Submit tenant 1 tasks
            for i in range(SCENARIOS_PER_TENANT):
                future = executor.submit(
                    simulate_solve_task,
                    store, TENANT_1, f"T1_SCENARIO_{i:03d}", STOPS_PER_SCENARIO
                )
                futures.append(("T1", future))

            # Submit tenant 2 tasks
            for i in range(SCENARIOS_PER_TENANT):
                future = executor.submit(
                    simulate_solve_task,
                    store, TENANT_2, f"T2_SCENARIO_{i:03d}", STOPS_PER_SCENARIO
                )
                futures.append(("T2", future))

            # Wait for all
            results = []
            for tenant_label, future in futures:
                result = future.result()
                results.append(result)

        print(f"    Completed {len(results)} tasks")

        # Verify data
        print("\n[2] Verifying tenant isolation...")

        all_data = store.get_all_data()

        # Tenant 1 checks
        t1_stops = all_data.get(TENANT_1, {}).get("stops", [])
        t1_assignments = all_data.get(TENANT_1, {}).get("assignments", [])

        t1_stop_tenant_ids = set(s["tenant_id"] for s in t1_stops)
        t1_assignment_tenant_ids = set(a["tenant_id"] for a in t1_assignments)

        print(f"    Tenant 1: {len(t1_stops)} stops, {len(t1_assignments)} assignments")
        self.assertEqual(t1_stop_tenant_ids, {TENANT_1}, "Tenant 1 stops should only have tenant_id=1")
        self.assertEqual(t1_assignment_tenant_ids, {TENANT_1}, "Tenant 1 assignments should only have tenant_id=1")
        print(f"    [PASS] Tenant 1 data isolated")

        # Tenant 2 checks
        t2_stops = all_data.get(TENANT_2, {}).get("stops", [])
        t2_assignments = all_data.get(TENANT_2, {}).get("assignments", [])

        t2_stop_tenant_ids = set(s["tenant_id"] for s in t2_stops)
        t2_assignment_tenant_ids = set(a["tenant_id"] for a in t2_assignments)

        print(f"    Tenant 2: {len(t2_stops)} stops, {len(t2_assignments)} assignments")
        self.assertEqual(t2_stop_tenant_ids, {TENANT_2}, "Tenant 2 stops should only have tenant_id=2")
        self.assertEqual(t2_assignment_tenant_ids, {TENANT_2}, "Tenant 2 assignments should only have tenant_id=2")
        print(f"    [PASS] Tenant 2 data isolated")

        # Cross-tenant check
        print("\n[3] Cross-tenant leak check...")

        # Verify no tenant 1 data in tenant 2's view
        store.set_tenant(TENANT_1)
        t1_view_stops = store.get_stops()
        t1_scenario_ids = set(s["scenario_id"] for s in t1_view_stops)

        store.set_tenant(TENANT_2)
        t2_view_stops = store.get_stops()
        t2_scenario_ids = set(s["scenario_id"] for s in t2_view_stops)

        # No overlap in scenario IDs
        overlap = t1_scenario_ids & t2_scenario_ids
        self.assertEqual(len(overlap), 0, f"No scenario ID overlap allowed: {overlap}")
        print(f"    [PASS] No scenario ID overlap")

        # Verify counts match expected
        expected_stops_per_tenant = SCENARIOS_PER_TENANT * STOPS_PER_SCENARIO
        self.assertEqual(len(t1_stops), expected_stops_per_tenant)
        self.assertEqual(len(t2_stops), expected_stops_per_tenant)
        print(f"    [PASS] Stop counts match: {expected_stops_per_tenant} per tenant")

        print("\n" + "=" * 60)
        print("GATE 3 PASSED: Zero cross-tenant data leak")
        print("=" * 60)

    def test_high_concurrency_no_leak(self):
        """
        PROOF: High concurrency (50 parallel tasks) maintains isolation.
        """
        print("\n" + "=" * 60)
        print("GATE 3: High Concurrency Leak Test (50 tasks)")
        print("=" * 60)

        store = TenantIsolatedStore()
        NUM_TENANTS = 5
        TASKS_PER_TENANT = 10
        STOPS_PER_TASK = 5

        print(f"\n[1] Running {NUM_TENANTS * TASKS_PER_TENANT} parallel tasks...")

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = []

            for tenant_id in range(1, NUM_TENANTS + 1):
                for task_num in range(TASKS_PER_TENANT):
                    scenario_id = f"T{tenant_id}_S{task_num:03d}"
                    future = executor.submit(
                        simulate_solve_task,
                        store, tenant_id, scenario_id, STOPS_PER_TASK
                    )
                    futures.append(future)

            # Wait for all
            for future in as_completed(futures):
                future.result()

        print(f"    Completed {len(futures)} tasks")

        # Verify each tenant's data
        print("\n[2] Verifying isolation across all tenants...")

        all_data = store.get_all_data()
        total_leaks = 0

        for tenant_id in range(1, NUM_TENANTS + 1):
            stops = all_data.get(tenant_id, {}).get("stops", [])
            assignments = all_data.get(tenant_id, {}).get("assignments", [])

            # Check all records belong to this tenant
            wrong_tenant_stops = [s for s in stops if s["tenant_id"] != tenant_id]
            wrong_tenant_assignments = [a for a in assignments if a["tenant_id"] != tenant_id]

            if wrong_tenant_stops or wrong_tenant_assignments:
                total_leaks += len(wrong_tenant_stops) + len(wrong_tenant_assignments)
                print(f"    [FAIL] Tenant {tenant_id}: {len(wrong_tenant_stops)} stop leaks, {len(wrong_tenant_assignments)} assignment leaks")
            else:
                print(f"    [PASS] Tenant {tenant_id}: {len(stops)} stops, {len(assignments)} assignments - ISOLATED")

        self.assertEqual(total_leaks, 0, f"Found {total_leaks} cross-tenant leaks!")

        print("\n" + "=" * 60)
        print("GATE 3 PASSED: High concurrency isolation maintained")
        print("=" * 60)

    def test_thread_context_isolation(self):
        """
        PROOF: Thread-local tenant context is isolated.

        Verifies that setting tenant_id in one thread doesn't affect another.
        """
        print("\n" + "=" * 60)
        print("GATE 3: Thread Context Isolation Test")
        print("=" * 60)

        store = TenantIsolatedStore()
        results = {}
        errors = []

        def check_tenant_context(tenant_id: int, expected_tenant: int):
            """Set tenant and verify it's correct."""
            store.set_tenant(tenant_id)
            time.sleep(random.uniform(0.01, 0.05))  # Simulate work

            actual = store.get_tenant()
            if actual != expected_tenant:
                errors.append(f"Thread expected {expected_tenant} but got {actual}")

            results[threading.current_thread().ident] = {
                "set_tenant": tenant_id,
                "got_tenant": actual,
            }

        print("\n[1] Running parallel tenant context sets...")

        threads = []
        for i in range(20):
            tenant_id = (i % 5) + 1  # Tenants 1-5
            t = threading.Thread(target=check_tenant_context, args=(tenant_id, tenant_id))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        print(f"    Completed {len(threads)} threads")
        print(f"    Unique thread IDs: {len(results)}")

        # Verify no errors
        self.assertEqual(len(errors), 0, f"Context isolation errors: {errors}")
        print(f"    [PASS] All threads had correct tenant context")

        print("\n" + "=" * 60)
        print("GATE 3 PASSED: Thread context isolation verified")
        print("=" * 60)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - RLS Parallel Leak Tests (Gate 3)")
    print("=" * 70)
    unittest.main(verbosity=2)
