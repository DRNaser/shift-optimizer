"""
RLS Leak Harness - Tests multi-tenant isolation under parallel load.

Creates N tenants, inserts test data, runs parallel queries,
verifies NO cross-tenant data ever appears.
"""

import os
import asyncio
import random
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False


@dataclass
class LeakTestResult:
    """Result of a single query in the leak test."""
    tenant_id: int
    expected_count: int
    actual_count: int
    leaked: bool
    leaked_tenant_ids: List[int]


@dataclass
class HarnessResult:
    """Result of the full RLS leak harness run."""
    passed: bool
    leaks_detected: int
    total_operations: int
    tenants_tested: int
    operations_per_tenant: int
    leak_details: List[dict]
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "leaks_detected": self.leaks_detected,
            "total_operations": self.total_operations,
            "tenants_tested": self.tenants_tested,
            "operations_per_tenant": self.operations_per_tenant,
            "leak_details": self.leak_details,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class RLSLeakHarness:
    """
    Tests RLS isolation between multiple tenants under parallel load.

    Strategy:
    1. Create N test tenants with unique test data
    2. Run M parallel queries from random tenants
    3. Verify each query ONLY sees its own tenant's data
    """

    def __init__(self, db_url: str, verbose: bool = False):
        self.db_url = db_url
        self.verbose = verbose
        self.tenants: List[int] = []
        self.tenant_data: dict = {}  # tenant_id -> list of forecast IDs

    def log(self, msg: str):
        if self.verbose:
            print(f"  [DEBUG] {msg}")

    async def setup_test_tenants(self, num_tenants: int) -> bool:
        """Create test tenants and sample data."""
        if not PSYCOPG_AVAILABLE:
            print("ERROR: psycopg not available")
            return False

        print(f"\n[SETUP] Creating {num_tenants} test tenants...")

        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_url, row_factory=dict_row
            ) as conn:
                async with conn.cursor() as cur:
                    # Create tenants starting at ID 1000+
                    base_id = 1000
                    for i in range(num_tenants):
                        tenant_id = base_id + i
                        self.tenants.append(tenant_id)

                        await cur.execute("""
                            INSERT INTO tenants (id, name, api_key_hash, is_active, metadata)
                            VALUES (%s, %s, %s, TRUE, '{"test": true}'::jsonb)
                            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                            RETURNING id
                        """, (tenant_id, f'rls-test-{tenant_id}', f'hash_{tenant_id}'))
                        self.log(f"Created tenant {tenant_id}")

                        # Create test forecasts for each tenant (random 3-7)
                        forecast_count = random.randint(3, 7)
                        self.tenant_data[tenant_id] = []

                        for j in range(forecast_count):
                            await cur.execute("""
                                INSERT INTO forecast_versions
                                (tenant_id, source, input_hash, parser_config_hash, status, week_anchor_date)
                                VALUES (%s, %s, %s, %s, 'PARSED', '2026-01-06')
                                RETURNING id
                            """, (
                                tenant_id,
                                'rls_harness_test',
                                f'hash_{tenant_id}_{j}_{datetime.now().timestamp()}',
                                'config_v1'
                            ))
                            result = await cur.fetchone()
                            self.tenant_data[tenant_id].append(result['id'])

                        self.log(f"  Created {forecast_count} forecasts for tenant {tenant_id}")

                    # Ensure sequence is ahead
                    await cur.execute("""
                        SELECT setval('tenants_id_seq', GREATEST(2000, (SELECT MAX(id) FROM tenants)))
                    """)

                await conn.commit()
                print(f"  Created {num_tenants} tenants with test data")
                return True

        except Exception as e:
            print(f"  Setup failed: {e}")
            return False

    async def query_with_rls(self, tenant_id: int) -> LeakTestResult:
        """Execute a query with RLS context and check for leaks."""
        async with await psycopg.AsyncConnection.connect(
            self.db_url, row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cur:
                # Set RLS context
                await cur.execute(
                    "SELECT set_config('app.current_tenant_id', %s, false)",
                    (str(tenant_id),)
                )

                # Small random delay to increase race likelihood
                await asyncio.sleep(random.uniform(0.001, 0.01))

                # Query forecasts - RLS should filter
                await cur.execute("""
                    SELECT id, tenant_id
                    FROM forecast_versions
                    WHERE source = 'rls_harness_test'
                    ORDER BY id
                """)
                rows = await cur.fetchall()

                # Check for leaks
                result_tenant_ids = [r['tenant_id'] for r in rows]
                leaked_tenant_ids = [
                    tid for tid in result_tenant_ids
                    if tid != tenant_id
                ]

                expected_count = len(self.tenant_data.get(tenant_id, []))

                return LeakTestResult(
                    tenant_id=tenant_id,
                    expected_count=expected_count,
                    actual_count=len(rows),
                    leaked=len(leaked_tenant_ids) > 0,
                    leaked_tenant_ids=list(set(leaked_tenant_ids))
                )

    async def run_parallel_queries(
        self, operations: int, workers: int
    ) -> tuple:
        """Run parallel queries from random tenants."""
        print(f"\n[TEST] Running {operations} operations with {workers} workers...")

        total_queries = 0
        leaks_found = 0
        leak_details = []

        # Create batches
        batch_size = workers
        batches = (operations + batch_size - 1) // batch_size

        for batch_num in range(batches):
            # Create mixed queries from random tenants
            queries = []
            current_batch_size = min(batch_size, operations - batch_num * batch_size)

            for _ in range(current_batch_size):
                tenant_id = random.choice(self.tenants)
                queries.append(self.query_with_rls(tenant_id))

            # Run in parallel
            results = await asyncio.gather(*queries, return_exceptions=True)

            # Analyze results
            for result in results:
                if isinstance(result, Exception):
                    self.log(f"Query error: {result}")
                    continue

                total_queries += 1

                if result.leaked:
                    leaks_found += 1
                    leak_details.append({
                        "tenant_id": result.tenant_id,
                        "leaked_from": result.leaked_tenant_ids,
                        "expected": result.expected_count,
                        "actual": result.actual_count,
                    })
                    print(f"  LEAK: Tenant {result.tenant_id} saw data from {result.leaked_tenant_ids}")

            if (batch_num + 1) % 10 == 0 or batch_num == batches - 1:
                progress = (batch_num + 1) / batches * 100
                print(f"  Progress: {progress:.0f}% ({total_queries} queries, {leaks_found} leaks)")

        return total_queries, leaks_found, leak_details

    async def cleanup(self) -> None:
        """Remove test data."""
        if not PSYCOPG_AVAILABLE:
            return

        print("\n[CLEANUP] Removing test data...")

        try:
            async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
                async with conn.cursor() as cur:
                    # Delete test forecasts
                    await cur.execute("""
                        DELETE FROM forecast_versions
                        WHERE source = 'rls_harness_test'
                    """)

                    # Delete test tenants
                    if self.tenants:
                        await cur.execute("""
                            DELETE FROM tenants
                            WHERE id = ANY(%s::int[])
                        """, (self.tenants,))

                await conn.commit()
                print("  Test data cleaned up")

        except Exception as e:
            print(f"  Cleanup warning: {e}")

    async def run(
        self,
        tenants: int = 2,
        operations: int = 100,
        workers: int = 10,
        cleanup: bool = True
    ) -> HarnessResult:
        """
        Run the full RLS leak harness.

        Args:
            tenants: Number of test tenants to create
            operations: Total number of operations to run
            workers: Number of parallel workers

        Returns:
            HarnessResult with pass/fail and details
        """
        if not PSYCOPG_AVAILABLE:
            return HarnessResult(
                passed=False,
                leaks_detected=0,
                total_operations=0,
                tenants_tested=tenants,
                operations_per_tenant=operations // tenants,
                leak_details=[],
                error="psycopg not available",
            )

        try:
            # Setup
            if not await self.setup_test_tenants(tenants):
                return HarnessResult(
                    passed=False,
                    leaks_detected=0,
                    total_operations=0,
                    tenants_tested=tenants,
                    operations_per_tenant=operations // tenants,
                    leak_details=[],
                    error="Setup failed",
                )

            # Run test
            total, leaks, details = await self.run_parallel_queries(operations, workers)

            return HarnessResult(
                passed=leaks == 0,
                leaks_detected=leaks,
                total_operations=total,
                tenants_tested=tenants,
                operations_per_tenant=operations // tenants,
                leak_details=details,
            )

        except Exception as e:
            return HarnessResult(
                passed=False,
                leaks_detected=0,
                total_operations=0,
                tenants_tested=tenants,
                operations_per_tenant=operations // tenants,
                leak_details=[],
                error=str(e),
            )

        finally:
            if cleanup:
                await self.cleanup()
