"""
Seed Default Policy Profiles

Creates and activates default policy profiles for all packs.
Run this script after applying migration 023_policy_profiles.sql.

Usage:
    python -m backend_py.api.scripts.seed_default_policies

Environment Variables:
    DATABASE_URL - PostgreSQL connection string
"""

import asyncio
import os
import sys
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from api.database import DatabaseManager
from api.services.policy_service import PolicyService, PolicyStatus


# =============================================================================
# DEFAULT CONFIGURATIONS
# =============================================================================

ROSTER_DEFAULT_CONFIG = {
    # Driver constraints (German labor law compliant defaults)
    "max_weekly_hours": 55,
    "min_rest_hours": 11,
    "max_span_regular_hours": 14,
    "max_span_split_hours": 16,

    # Split break constraints
    "min_split_break_minutes": 240,
    "max_split_break_minutes": 360,

    # Block construction
    "min_gap_between_tours_minutes": 30,
    "max_gap_between_tours_minutes": 60,

    # Optimization preferences
    "optimization_goal": "minimize_drivers",
    "prefer_fte_over_pt": True,
    "minimize_splits": True,
    "allow_3er_consecutive": False,

    # Solver settings
    "solver_time_limit_seconds": 300,
    "seed": 94,
    "refinement_passes": 3,

    # Audit settings
    "fail_on_audit_warning": False,
    "required_coverage_percent": 100.0,
}

ROUTING_DEFAULT_CONFIG = {
    # Vehicle constraints
    "max_route_duration_hours": 10,
    "max_stops_per_route": 50,
    "default_service_time_minutes": 15,

    # Time window handling
    "time_window_slack_minutes": 15,
    "allow_waiting": True,
    "max_waiting_minutes": 30,

    # Solver settings
    "solver_time_limit_seconds": 300,
    "metaheuristic": "GUIDED_LOCAL_SEARCH",
    "solution_limit": 100,

    # Freeze/lock settings
    "freeze_horizon_minutes": 60,
    "auto_lock_on_dispatch": True,

    # Evidence settings
    "require_evidence_hash": True,
    "artifact_retention_days": 90,
}


# =============================================================================
# SEED FUNCTION
# =============================================================================

async def seed_default_policies(tenant_id: str, tenant_name: str = "system"):
    """
    Seed default policy profiles for a tenant.

    Args:
        tenant_id: UUID of the tenant
        tenant_name: Name for audit trail (created_by field)
    """
    db_manager = DatabaseManager()
    await db_manager.initialize()

    try:
        policy_service = PolicyService(db_manager.pool)

        # Check if profiles already exist
        existing = await policy_service.list_profiles(tenant_id)
        existing_names = {p.name for p in existing}

        results = []

        # Seed roster default if not exists
        if "roster_default_v1" not in existing_names:
            print(f"Creating roster_default_v1 for tenant {tenant_id}...")
            roster_id = await policy_service.create_profile(
                tenant_id=tenant_id,
                pack_id="roster",
                name="roster_default_v1",
                config=ROSTER_DEFAULT_CONFIG,
                created_by=tenant_name,
                description="Default roster pack configuration (German labor law compliant)",
                schema_version="1.0",
            )

            # Activate the profile
            await policy_service.activate_profile(roster_id, activated_by=tenant_name)

            # Set as active for the pack
            await policy_service.set_active_profile(
                tenant_id=tenant_id,
                pack_id="roster",
                profile_id=roster_id,
                updated_by=tenant_name,
            )

            results.append(("roster_default_v1", roster_id, "CREATED + ACTIVATED"))
            print(f"  Created and activated roster_default_v1: {roster_id}")
        else:
            print(f"  roster_default_v1 already exists, skipping")
            results.append(("roster_default_v1", None, "SKIPPED (exists)"))

        # Seed routing default if not exists
        if "routing_default_v1" not in existing_names:
            print(f"Creating routing_default_v1 for tenant {tenant_id}...")
            routing_id = await policy_service.create_profile(
                tenant_id=tenant_id,
                pack_id="routing",
                name="routing_default_v1",
                config=ROUTING_DEFAULT_CONFIG,
                created_by=tenant_name,
                description="Default routing pack configuration (Wien pilot)",
                schema_version="1.0",
            )

            # Activate the profile
            await policy_service.activate_profile(routing_id, activated_by=tenant_name)

            # Set as active for the pack
            await policy_service.set_active_profile(
                tenant_id=tenant_id,
                pack_id="routing",
                profile_id=routing_id,
                updated_by=tenant_name,
            )

            results.append(("routing_default_v1", routing_id, "CREATED + ACTIVATED"))
            print(f"  Created and activated routing_default_v1: {routing_id}")
        else:
            print(f"  routing_default_v1 already exists, skipping")
            results.append(("routing_default_v1", None, "SKIPPED (exists)"))

        return results

    finally:
        await db_manager.close()


async def seed_all_tenants():
    """Seed default policies for all tenants in the system."""
    db_manager = DatabaseManager()
    await db_manager.initialize()

    try:
        async with db_manager.pool.connection() as conn:
            # Get all core tenants
            rows = await conn.execute("""
                SELECT id, code, display_name
                FROM core.tenants
                WHERE is_active = true
            """)
            tenants = await rows.fetchall()

            if not tenants:
                print("No active tenants found in core.tenants")
                print("Checking legacy tenants table...")

                # Fallback to legacy tenants table
                rows = await conn.execute("""
                    SELECT tenant_id::text as id, name as code, name as display_name
                    FROM tenants
                    WHERE is_active = true OR is_active IS NULL
                """)
                tenants = await rows.fetchall()

            if not tenants:
                print("No tenants found. Creating seed for default tenant ID.")
                # Use a placeholder UUID for development
                tenants = [{"id": "00000000-0000-0000-0000-000000000001", "code": "LTS", "display_name": "LTS Transport"}]

        print(f"Found {len(tenants)} tenant(s)")

        all_results = {}
        for tenant in tenants:
            tenant_id = str(tenant["id"]) if isinstance(tenant, dict) else str(tenant[0])
            tenant_name = tenant.get("display_name", tenant.get("code", "system")) if isinstance(tenant, dict) else tenant[2]

            print(f"\n=== Seeding tenant: {tenant_name} ({tenant_id}) ===")
            results = await seed_default_policies(tenant_id, tenant_name)
            all_results[tenant_id] = results

        return all_results

    finally:
        await db_manager.close()


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed default policy profiles")
    parser.add_argument(
        "--tenant-id",
        help="Specific tenant UUID to seed (default: all tenants)",
    )
    parser.add_argument(
        "--tenant-name",
        default="system",
        help="Name for audit trail (default: system)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("SOLVEREIGN - Default Policy Profile Seeder")
    print("=" * 60)
    print()

    if args.tenant_id:
        results = asyncio.run(seed_default_policies(args.tenant_id, args.tenant_name))
    else:
        results = asyncio.run(seed_all_tenants())

    print()
    print("=" * 60)
    print("SEED COMPLETE")
    print("=" * 60)

    # Summary
    if isinstance(results, dict):
        for tenant_id, tenant_results in results.items():
            print(f"\nTenant {tenant_id}:")
            for name, profile_id, status in tenant_results:
                print(f"  {name}: {status}")
    else:
        for name, profile_id, status in results:
            print(f"  {name}: {status}")
