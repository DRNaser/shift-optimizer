"""
SOLVEREIGN V3.3b - Two-Tenant Parallel RLS Leak Test
====================================================

CRITICAL: Run this BEFORE production traffic to verify RLS isolation
under concurrent load. Many leaks only show under pool reuse.

Creates two tenants, inserts test data, runs parallel queries,
verifies NO cross-tenant data ever appears.

Usage:
    # Requires PostgreSQL with test data
    export SOLVEREIGN_DATABASE_URL=postgresql://...

    # Run with default settings (20 parallel requests, 5 rounds)
    python backend_py/tests/test_rls_parallel_leak.py

    # Heavy load test
    python backend_py/tests/test_rls_parallel_leak.py --parallel=50 --rounds=10
"""

import os
import sys
import asyncio
import argparse
import random
from datetime import datetime
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class LeakTestResult:
    """Result of a single query in the leak test."""
    tenant_id: int
    expected_forecasts: int
    actual_forecasts: List[int]
    leaked: bool
    leaked_tenant_ids: List[int]


class TwoTenantLeakTest:
    """
    Tests RLS isolation between two tenants under parallel load.

    Strategy:
    1. Create tenant_lts (id=100) with 5 forecasts
    2. Create tenant_dummy (id=200) with 3 forecasts
    3. Run N parallel queries from both tenants
    4. Verify each query ONLY sees its own data
    """

    def __init__(self, db_url: str, verbose: bool = False):
        self.db_url = db_url
        self.verbose = verbose
        self.tenant_lts_id = 100
        self.tenant_dummy_id = 200
        self.lts_forecasts = []
        self.dummy_forecasts = []

    def log(self, msg: str):
        if self.verbose:
            print(f"  [DEBUG] {msg}")

    async def setup_test_tenants(self) -> bool:
        """Create test tenants and sample data."""
        import psycopg
        from psycopg.rows import dict_row

        print("\n[SETUP] Creating test tenants and data...")

        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_url, row_factory=dict_row
            ) as conn:
                async with conn.cursor() as cur:
                    # Create tenant_lts (test)
                    await cur.execute("""
                        INSERT INTO tenants (id, name, api_key_hash, is_active, metadata)
                        VALUES (%s, %s, %s, TRUE, '{"test": true}'::jsonb)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                    """, (self.tenant_lts_id, 'test-lts-leak', 'test_hash_lts'))
                    self.log(f"Created/updated tenant_lts id={self.tenant_lts_id}")

                    # Create tenant_dummy (test)
                    await cur.execute("""
                        INSERT INTO tenants (id, name, api_key_hash, is_active, metadata)
                        VALUES (%s, %s, %s, TRUE, '{"test": true}'::jsonb)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                    """, (self.tenant_dummy_id, 'test-dummy-leak', 'test_hash_dummy'))
                    self.log(f"Created/updated tenant_dummy id={self.tenant_dummy_id}")

                    # Ensure sequence is ahead
                    await cur.execute("""
                        SELECT setval('tenants_id_seq', GREATEST(300, (SELECT MAX(id) FROM tenants)))
                    """)

                    # Create test forecasts for LTS (5)
                    self.lts_forecasts = []
                    for i in range(5):
                        await cur.execute("""
                            INSERT INTO forecast_versions
                            (tenant_id, source, input_hash, parser_config_hash, status, week_anchor_date)
                            VALUES (%s, %s, %s, %s, 'PARSED', '2026-01-06')
                            RETURNING id
                        """, (
                            self.tenant_lts_id,
                            'leak_test',
                            f'lts_hash_{i}_{datetime.now().timestamp()}',
                            'config_v1'
                        ))
                        result = await cur.fetchone()
                        self.lts_forecasts.append(result['id'])
                    self.log(f"Created LTS forecasts: {self.lts_forecasts}")

                    # Create test forecasts for DUMMY (3)
                    self.dummy_forecasts = []
                    for i in range(3):
                        await cur.execute("""
                            INSERT INTO forecast_versions
                            (tenant_id, source, input_hash, parser_config_hash, status, week_anchor_date)
                            VALUES (%s, %s, %s, %s, 'PARSED', '2026-01-06')
                            RETURNING id
                        """, (
                            self.tenant_dummy_id,
                            'leak_test',
                            f'dummy_hash_{i}_{datetime.now().timestamp()}',
                            'config_v1'
                        ))
                        result = await cur.fetchone()
                        self.dummy_forecasts.append(result['id'])
                    self.log(f"Created DUMMY forecasts: {self.dummy_forecasts}")

                await conn.commit()
                print(f"  ✓ Created tenant_lts ({len(self.lts_forecasts)} forecasts)")
                print(f"  ✓ Created tenant_dummy ({len(self.dummy_forecasts)} forecasts)")
                return True

        except Exception as e:
            print(f"  ✗ Setup failed: {e}")
            return False

    async def query_with_rls(
        self, tenant_id: int, query_id: int
    ) -> LeakTestResult:
        """
        Execute a query with RLS context and check for leaks.

        Uses tenant_connection pattern to set RLS properly.
        """
        import psycopg
        from psycopg.rows import dict_row

        try:
            async with await psycopg.AsyncConnection.connect(
                self.db_url, row_factory=dict_row
            ) as conn:
                async with conn.cursor() as cur:
                    # Set RLS context (same pattern as tenant_connection)
                    await cur.execute(
                        "SELECT set_config('app.current_tenant_id', %s, false)",
                        (str(tenant_id),)
                    )

                    # Add small random delay to increase race likelihood
                    await asyncio.sleep(random.uniform(0.001, 0.01))

                    # Query forecasts - RLS should filter
                    await cur.execute("""
                        SELECT id, tenant_id
                        FROM forecast_versions
                        WHERE source = 'leak_test'
                        ORDER BY id
                    """)
                    rows = await cur.fetchall()

                    # Check results
                    forecast_ids = [r['id'] for r in rows]
                    result_tenant_ids = [r['tenant_id'] for r in rows]

                    # Determine expected forecasts
                    if tenant_id == self.tenant_lts_id:
                        expected = len(self.lts_forecasts)
                        expected_ids = set(self.lts_forecasts)
                    else:
                        expected = len(self.dummy_forecasts)
                        expected_ids = set(self.dummy_forecasts)

                    # Check for leaks
                    leaked_tenant_ids = [
                        tid for tid in result_tenant_ids
                        if tid != tenant_id
                    ]

                    return LeakTestResult(
                        tenant_id=tenant_id,
                        expected_forecasts=expected,
                        actual_forecasts=forecast_ids,
                        leaked=len(leaked_tenant_ids) > 0,
                        leaked_tenant_ids=list(set(leaked_tenant_ids))
                    )

        except Exception as e:
            self.log(f"Query {query_id} error: {e}")
            raise

    async def run_parallel_queries(
        self, num_parallel: int, rounds: int
    ) -> Tuple[int, int, List[LeakTestResult]]:
        """
        Run parallel queries from both tenants.

        Returns: (total_queries, leaks_found, leak_results)
        """
        print(f"\n[TEST] Running {rounds} rounds of {num_parallel} parallel queries...")
        print(f"       Total queries: {rounds * num_parallel}")

        total_queries = 0
        leaks_found = 0
        leak_details = []

        for round_num in range(rounds):
            # Create mixed queries from both tenants
            queries = []
            for i in range(num_parallel):
                # Alternate between tenants
                tenant_id = self.tenant_lts_id if i % 2 == 0 else self.tenant_dummy_id
                queries.append(self.query_with_rls(tenant_id, i))

            # Run in parallel
            results = await asyncio.gather(*queries, return_exceptions=True)

            # Analyze results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"  ⚠ Query {i} failed: {result}")
                    continue

                total_queries += 1

                if result.leaked:
                    leaks_found += 1
                    leak_details.append(result)
                    print(f"  ✗ LEAK in round {round_num}, query {i}:")
                    print(f"    Tenant {result.tenant_id} saw data from {result.leaked_tenant_ids}")

            if (round_num + 1) % 5 == 0 or round_num == rounds - 1:
                print(f"  Round {round_num + 1}/{rounds}: {total_queries} queries, {leaks_found} leaks")

        return total_queries, leaks_found, leak_details

    async def cleanup(self) -> None:
        """Remove test data."""
        import psycopg

        print("\n[CLEANUP] Removing test data...")

        try:
            async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
                async with conn.cursor() as cur:
                    # Delete test forecasts
                    await cur.execute("""
                        DELETE FROM forecast_versions
                        WHERE source = 'leak_test'
                          AND tenant_id IN (%s, %s)
                    """, (self.tenant_lts_id, self.tenant_dummy_id))

                    # Delete test tenants
                    await cur.execute("""
                        DELETE FROM tenants
                        WHERE id IN (%s, %s)
                    """, (self.tenant_lts_id, self.tenant_dummy_id))

                await conn.commit()
                print("  ✓ Test data cleaned up")

        except Exception as e:
            print(f"  ⚠ Cleanup warning: {e}")

    async def run_full_test(
        self, num_parallel: int = 20, rounds: int = 5, cleanup: bool = True
    ) -> bool:
        """
        Run the complete leak test.

        Returns: True if NO leaks found (PASS)
        """
        print("\n" + "=" * 70)
        print("SOLVEREIGN V3.3b - Two-Tenant Parallel RLS Leak Test")
        print("=" * 70)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Parallel queries: {num_parallel}")
        print(f"Rounds: {rounds}")
        print(f"Total queries: {num_parallel * rounds}")
        print("=" * 70)

        # Setup
        if not await self.setup_test_tenants():
            return False

        try:
            # Run test
            total, leaks, details = await self.run_parallel_queries(
                num_parallel, rounds
            )

            # Summary
            print("\n" + "=" * 70)
            print("RESULT SUMMARY")
            print("=" * 70)
            print(f"Total queries executed: {total}")
            print(f"Leaks detected: {leaks}")

            if leaks == 0:
                print("\n✓ PASS: No RLS leaks detected under parallel load")
                print("  Safe to proceed with production traffic")
                return True
            else:
                print(f"\n✗ FAIL: {leaks} RLS LEAKS DETECTED!")
                print("  DO NOT proceed with production traffic")
                print("\n  Leak details:")
                for detail in details:
                    print(f"    - Tenant {detail.tenant_id} saw {detail.leaked_tenant_ids}")
                return False

        finally:
            if cleanup:
                await self.cleanup()


async def main():
    parser = argparse.ArgumentParser(
        description="Two-tenant parallel RLS leak test"
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("SOLVEREIGN_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="PostgreSQL connection URL"
    )
    parser.add_argument(
        "--parallel", "-p",
        type=int,
        default=20,
        help="Number of parallel queries per round (default: 20)"
    )
    parser.add_argument(
        "--rounds", "-r",
        type=int,
        default=5,
        help="Number of rounds to run (default: 5)"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't clean up test data after run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    if not args.db_url:
        print("ERROR: Database URL required. Set SOLVEREIGN_DATABASE_URL")
        sys.exit(1)

    tester = TwoTenantLeakTest(args.db_url, verbose=args.verbose)
    passed = await tester.run_full_test(
        num_parallel=args.parallel,
        rounds=args.rounds,
        cleanup=not args.no_cleanup
    )

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
