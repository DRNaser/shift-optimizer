#!/usr/bin/env python3
"""
MINI-TEST 2: Impact Preview Active Freeze Blocking Test (Skill 114)

Purpose: Verify that disabling a pack with active LOCKED plans and frozen scope
         returns BLOCKED status with clear "why" reasons.

Test Scenario:
1. Tenant has routing pack enabled
2. Tenant has LOCKED plans (immutable, in production)
3. Some routes are within freeze horizon (60 min before start)
4. Admin attempts to disable routing pack
5. Expected: BLOCKED with reasons:
   - "X active locked plans would be affected"
   - "Y routes within freeze horizon"
   - "Cannot disable pack with frozen scope"

Exit Codes:
- 0: PASS - BLOCKED with correct reasons
- 1: FAIL - Not blocked or missing reasons
- 2: ERROR - Test infrastructure failure
"""

import json
import sys
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# ============================================
# RISK LEVEL ENUM (from 114 skill)
# ============================================

class RiskLevel(Enum):
    SAFE = "SAFE"           # Green - no risk
    CAUTION = "CAUTION"     # Yellow - minor risk
    RISKY = "RISKY"         # Orange - approval required
    BLOCKED = "BLOCKED"     # Red - policy blocked


# ============================================
# TEST DATA STRUCTURES
# ============================================

@dataclass
class MockPlan:
    plan_id: str
    tenant_id: str
    pack_name: str
    status: str  # DRAFT, LOCKED
    route_count: int
    created_at: datetime


@dataclass
class MockRoute:
    route_id: str
    plan_id: str
    start_time: datetime
    is_locked: bool = False  # DB flag
    # Computed: frozen if within horizon of start_time


@dataclass
class MockTenant:
    tenant_id: str
    tenant_code: str
    packs_enabled: List[str]
    plans: List[MockPlan] = field(default_factory=list)
    routes: List[MockRoute] = field(default_factory=list)


@dataclass
class ImpactPreviewResult:
    risk_level: RiskLevel
    blocking_reasons: List[str]
    affected_plans: List[str]
    affected_routes: List[str]
    warnings: List[str]
    can_proceed: bool
    recommended_action: str


# ============================================
# IMPACT ANALYZER (Simulates 114 skill logic)
# ============================================

class ImpactAnalyzer:
    """
    Analyzes the impact of pack operations on tenants.
    This mirrors the logic in 114-change-impact-analyzer.md
    """

    def __init__(self, freeze_horizon_minutes: int = 60):
        self.freeze_horizon_minutes = freeze_horizon_minutes

    def analyze_pack_disable(
        self,
        tenant: MockTenant,
        pack_name: str,
        current_time: Optional[datetime] = None
    ) -> ImpactPreviewResult:
        """
        Analyze impact of disabling a pack for a tenant.

        BLOCKING CONDITIONS:
        1. Any LOCKED plans using this pack
        2. Any routes within freeze horizon
        3. Any routes with is_locked=TRUE in DB
        """
        if current_time is None:
            current_time = datetime.utcnow()

        blocking_reasons = []
        warnings = []
        affected_plans = []
        affected_routes = []

        # Check 1: Pack not enabled (invalid operation)
        if pack_name not in tenant.packs_enabled:
            return ImpactPreviewResult(
                risk_level=RiskLevel.SAFE,
                blocking_reasons=[],
                affected_plans=[],
                affected_routes=[],
                warnings=[f"Pack '{pack_name}' is not enabled for tenant"],
                can_proceed=True,
                recommended_action="No action needed - pack already disabled"
            )

        # Check 2: LOCKED plans using this pack
        locked_plans = [
            p for p in tenant.plans
            if p.pack_name == pack_name and p.status == "LOCKED"
        ]

        if locked_plans:
            affected_plans = [p.plan_id for p in locked_plans]
            blocking_reasons.append(
                f"{len(locked_plans)} active LOCKED plan(s) would be affected: {', '.join(affected_plans)}"
            )

        # Check 3: Routes within freeze horizon
        freeze_cutoff = current_time + timedelta(minutes=self.freeze_horizon_minutes)

        frozen_routes = []
        for route in tenant.routes:
            # Check if route belongs to a plan using this pack
            parent_plan = next(
                (p for p in tenant.plans if p.plan_id == route.plan_id),
                None
            )
            if parent_plan and parent_plan.pack_name == pack_name:
                # Check freeze conditions
                is_frozen = False
                freeze_reason = None

                if route.is_locked:
                    is_frozen = True
                    freeze_reason = "DB locked"
                elif route.start_time <= freeze_cutoff:
                    is_frozen = True
                    freeze_reason = f"starts within {self.freeze_horizon_minutes}min"

                if is_frozen:
                    frozen_routes.append((route.route_id, freeze_reason))

        if frozen_routes:
            affected_routes = [r[0] for r in frozen_routes]
            blocking_reasons.append(
                f"{len(frozen_routes)} route(s) within freeze scope: "
                f"{', '.join([f'{r[0]} ({r[1]})' for r in frozen_routes[:3]])}"
                + (f" and {len(frozen_routes) - 3} more..." if len(frozen_routes) > 3 else "")
            )

        # Determine risk level
        if blocking_reasons:
            risk_level = RiskLevel.BLOCKED
            can_proceed = False
            recommended_action = (
                "Cannot disable pack with frozen scope. "
                "Wait for frozen routes to complete or contact PLATFORM_ADMIN for override."
            )
        elif len(tenant.plans) > 0:
            # Has plans but none locked/frozen - still risky
            risk_level = RiskLevel.RISKY
            can_proceed = True
            warnings.append(
                f"Tenant has {len(tenant.plans)} plan(s) that may be affected"
            )
            recommended_action = "Proceed with caution - notify tenant before disabling"
        else:
            risk_level = RiskLevel.SAFE
            can_proceed = True
            recommended_action = "Safe to proceed"

        return ImpactPreviewResult(
            risk_level=risk_level,
            blocking_reasons=blocking_reasons,
            affected_plans=affected_plans,
            affected_routes=affected_routes,
            warnings=warnings,
            can_proceed=can_proceed,
            recommended_action=recommended_action
        )


# ============================================
# TEST FIXTURE
# ============================================

def create_test_tenant() -> MockTenant:
    """
    Create a tenant with:
    - routing pack enabled
    - 2 LOCKED plans
    - 1 DRAFT plan
    - Routes within freeze horizon
    - Routes with is_locked=TRUE
    """
    now = datetime.utcnow()

    tenant = MockTenant(
        tenant_id="tenant-001",
        tenant_code="MEDIAMARKT",
        packs_enabled=["routing", "roster"],
        plans=[],
        routes=[]
    )

    # Add plans
    tenant.plans = [
        MockPlan(
            plan_id="plan-locked-001",
            tenant_id="tenant-001",
            pack_name="routing",
            status="LOCKED",
            route_count=15,
            created_at=now - timedelta(hours=2)
        ),
        MockPlan(
            plan_id="plan-locked-002",
            tenant_id="tenant-001",
            pack_name="routing",
            status="LOCKED",
            route_count=8,
            created_at=now - timedelta(hours=1)
        ),
        MockPlan(
            plan_id="plan-draft-001",
            tenant_id="tenant-001",
            pack_name="routing",
            status="DRAFT",
            route_count=5,
            created_at=now - timedelta(minutes=30)
        ),
    ]

    # Add routes
    tenant.routes = [
        # Routes in plan-locked-001 (frozen by time)
        MockRoute(
            route_id="route-001",
            plan_id="plan-locked-001",
            start_time=now + timedelta(minutes=30),  # Starts in 30 min (frozen!)
            is_locked=False
        ),
        MockRoute(
            route_id="route-002",
            plan_id="plan-locked-001",
            start_time=now + timedelta(minutes=45),  # Starts in 45 min (frozen!)
            is_locked=False
        ),
        MockRoute(
            route_id="route-003",
            plan_id="plan-locked-001",
            start_time=now + timedelta(hours=3),  # Starts in 3h (NOT frozen)
            is_locked=False
        ),

        # Routes in plan-locked-002 (frozen by DB flag)
        MockRoute(
            route_id="route-004",
            plan_id="plan-locked-002",
            start_time=now + timedelta(hours=5),  # Far future but DB locked
            is_locked=True  # Explicit DB lock!
        ),
        MockRoute(
            route_id="route-005",
            plan_id="plan-locked-002",
            start_time=now + timedelta(hours=6),
            is_locked=False
        ),

        # Routes in draft plan (not relevant)
        MockRoute(
            route_id="route-006",
            plan_id="plan-draft-001",
            start_time=now + timedelta(minutes=20),
            is_locked=False
        ),
    ]

    return tenant


# ============================================
# TEST EXECUTION
# ============================================

def run_active_freeze_test() -> Dict[str, Any]:
    """
    Run the active freeze blocking test.

    Expected Result:
    - risk_level == BLOCKED
    - blocking_reasons contains both:
      - Reference to LOCKED plans
      - Reference to frozen routes
    """
    tenant = create_test_tenant()
    analyzer = ImpactAnalyzer(freeze_horizon_minutes=60)

    # Analyze: What happens if we disable routing pack?
    result = analyzer.analyze_pack_disable(
        tenant=tenant,
        pack_name="routing",
        current_time=datetime.utcnow()
    )

    # Validate expectations
    checks = {
        "risk_level_is_blocked": result.risk_level == RiskLevel.BLOCKED,
        "has_blocking_reasons": len(result.blocking_reasons) > 0,
        "mentions_locked_plans": any("LOCKED" in r for r in result.blocking_reasons),
        "mentions_frozen_routes": any("freeze" in r.lower() or "route" in r.lower() for r in result.blocking_reasons),
        "cannot_proceed": result.can_proceed == False,
        "has_affected_plans": len(result.affected_plans) > 0,
        "has_affected_routes": len(result.affected_routes) > 0,
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "result": {
            "risk_level": result.risk_level.value,
            "blocking_reasons": result.blocking_reasons,
            "affected_plans": result.affected_plans,
            "affected_routes": result.affected_routes,
            "can_proceed": result.can_proceed,
            "recommended_action": result.recommended_action,
        }
    }


def main():
    """Main entry point for CI integration."""
    print("=" * 60)
    print("MINI-TEST 2: Impact Preview Active Freeze Test (Skill 114)")
    print("=" * 60)
    print()

    print("Test Scenario:")
    print("  - Tenant: MEDIAMARKT (tenant-001)")
    print("  - Pack: routing (enabled)")
    print("  - Plans: 2 LOCKED, 1 DRAFT")
    print("  - Routes: 3 frozen (2 by time, 1 by DB lock)")
    print("  - Action: Disable routing pack")
    print("  - Expected: BLOCKED")
    print()

    # Run test
    test_result = run_active_freeze_test()

    # Report results
    print("Check Results:")
    for check_name, passed in test_result["checks"].items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")
    print()

    print("Impact Analysis Result:")
    print(f"  Risk Level: {test_result['result']['risk_level']}")
    print(f"  Can Proceed: {test_result['result']['can_proceed']}")
    print()

    print("Blocking Reasons:")
    for reason in test_result['result']['blocking_reasons']:
        print(f"  - {reason}")
    print()

    print(f"Affected Plans: {test_result['result']['affected_plans']}")
    print(f"Affected Routes: {test_result['result']['affected_routes']}")
    print()
    print(f"Recommended Action: {test_result['result']['recommended_action']}")
    print()

    if test_result["passed"]:
        print("RESULT: PASS")
        print()
        print("Impact Preview correctly returned BLOCKED with clear reasons.")
        sys.exit(0)
    else:
        print("RESULT: FAIL")
        print()
        print("Impact Preview did not return expected BLOCKED status or missing reasons.")
        failed_checks = [k for k, v in test_result["checks"].items() if not v]
        print(f"Failed checks: {failed_checks}")
        sys.exit(1)


if __name__ == "__main__":
    main()
