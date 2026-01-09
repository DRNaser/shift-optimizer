"""
SOLVEREIGN SaaS - Solver Run Service
=====================================

PostgreSQL-backed service for managing solver runs and plan state machine.

State Machine: DRAFT -> SOLVING -> SOLVED -> APPROVED -> PUBLISHED

Key Features:
- Persistent run storage (survives restarts)
- State transitions with audit trail
- Evidence linking (artifact URIs)
- Multi-tenant isolation (RLS)
"""

import uuid
import asyncio
import hashlib
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

import asyncpg
from pydantic import BaseModel


# =============================================================================
# MODELS
# =============================================================================

class SolverRunCreate(BaseModel):
    """Request to create a solver run."""
    tenant_id: int
    site_id: int
    plan_version_id: Optional[int] = None
    solver_type: str = "VRPTW"
    solver_version: str = "3.6.5"
    seed: Optional[int] = None
    time_limit_seconds: int = 300
    input_hash: str
    matrix_hash: str
    policy_hash: Optional[str] = None
    multi_start_enabled: bool = False
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = {}


class SolverRunUpdate(BaseModel):
    """Update to a solver run."""
    status: Optional[str] = None
    kpi_unassigned: Optional[int] = None
    kpi_vehicles_used: Optional[int] = None
    kpi_total_distance_km: Optional[float] = None
    kpi_total_duration_min: Optional[float] = None
    kpi_overtime_min: Optional[float] = None
    kpi_coverage_pct: Optional[float] = None
    multi_start_runs_total: Optional[int] = None
    multi_start_best_seed: Optional[int] = None
    multi_start_scores: Optional[Dict] = None
    output_hash: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    result_artifact_uri: Optional[str] = None
    evidence_artifact_uri: Optional[str] = None


class PlanStateTransition(BaseModel):
    """Request to transition plan state."""
    to_state: str
    performed_by: str
    reason: Optional[str] = None
    kpi_snapshot: Optional[Dict] = None


@dataclass
class SolverRun:
    """Solver run entity."""
    run_id: str
    tenant_id: int
    site_id: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    plan_version_id: Optional[int] = None
    solver_type: str = "VRPTW"
    solver_version: str = "3.6.5"
    seed: Optional[int] = None
    input_hash: str = ""
    matrix_hash: str = ""
    output_hash: Optional[str] = None
    kpi_unassigned: Optional[int] = None
    kpi_vehicles_used: Optional[int] = None
    kpi_coverage_pct: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "site_id": self.site_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "plan_version_id": self.plan_version_id,
            "solver_type": self.solver_type,
            "solver_version": self.solver_version,
            "seed": self.seed,
            "input_hash": self.input_hash,
            "matrix_hash": self.matrix_hash,
            "output_hash": self.output_hash,
            "kpi_unassigned": self.kpi_unassigned,
            "kpi_vehicles_used": self.kpi_vehicles_used,
            "kpi_coverage_pct": self.kpi_coverage_pct,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


# =============================================================================
# SERVICE
# =============================================================================

class SolverRunService:
    """
    PostgreSQL-backed service for solver runs.

    Replaces in-memory RunStore with persistent storage.
    Uses RLS for multi-tenant isolation.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create_run(self, data: SolverRunCreate) -> SolverRun:
        """Create a new solver run."""
        run_id = str(uuid.uuid4())

        async with self.pool.acquire() as conn:
            # Set tenant context for RLS
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1::text, true)",
                str(data.tenant_id)
            )

            await conn.execute("""
                INSERT INTO solver_runs (
                    run_id, tenant_id, site_id, plan_version_id,
                    solver_type, solver_version, seed, time_limit_seconds,
                    input_hash, matrix_hash, policy_hash,
                    multi_start_enabled, created_by, metadata, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, 'PENDING')
            """,
                run_id, data.tenant_id, data.site_id, data.plan_version_id,
                data.solver_type, data.solver_version, data.seed, data.time_limit_seconds,
                data.input_hash, data.matrix_hash, data.policy_hash,
                data.multi_start_enabled, data.created_by,
                json.dumps(data.metadata) if data.metadata else "{}"
            )

        return SolverRun(
            run_id=run_id,
            tenant_id=data.tenant_id,
            site_id=data.site_id,
            status="PENDING",
            started_at=datetime.utcnow(),
            plan_version_id=data.plan_version_id,
            solver_type=data.solver_type,
            solver_version=data.solver_version,
            seed=data.seed,
            input_hash=data.input_hash,
            matrix_hash=data.matrix_hash,
        )

    async def get_run(self, run_id: str, tenant_id: int) -> Optional[SolverRun]:
        """Get a solver run by ID."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1::text, true)",
                str(tenant_id)
            )

            row = await conn.fetchrow("""
                SELECT run_id, tenant_id, site_id, status, started_at, completed_at,
                       plan_version_id, solver_type, solver_version, seed,
                       input_hash, matrix_hash, output_hash,
                       kpi_unassigned, kpi_vehicles_used, kpi_coverage_pct,
                       error_code, error_message
                FROM solver_runs
                WHERE run_id = $1::uuid
            """, uuid.UUID(run_id))

            if not row:
                return None

            return SolverRun(
                run_id=str(row["run_id"]),
                tenant_id=row["tenant_id"],
                site_id=row["site_id"],
                status=row["status"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                plan_version_id=row["plan_version_id"],
                solver_type=row["solver_type"],
                solver_version=row["solver_version"],
                seed=row["seed"],
                input_hash=row["input_hash"],
                matrix_hash=row["matrix_hash"],
                output_hash=row["output_hash"],
                kpi_unassigned=row["kpi_unassigned"],
                kpi_vehicles_used=row["kpi_vehicles_used"],
                kpi_coverage_pct=row["kpi_coverage_pct"],
                error_code=row["error_code"],
                error_message=row["error_message"],
            )

    async def update_run(self, run_id: str, tenant_id: int, data: SolverRunUpdate) -> bool:
        """Update a solver run."""
        updates = []
        values = []
        idx = 1

        for field_name, value in data.model_dump(exclude_none=True).items():
            if field_name == "multi_start_scores" and value:
                value = json.dumps(value)
            updates.append(f"{field_name} = ${idx}")
            values.append(value)
            idx += 1

        if not updates:
            return True

        # Add completed_at if status is terminal
        if data.status in ("SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"):
            updates.append(f"completed_at = ${idx}")
            values.append(datetime.utcnow())
            idx += 1

        values.append(uuid.UUID(run_id))

        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1::text, true)",
                str(tenant_id)
            )

            result = await conn.execute(f"""
                UPDATE solver_runs
                SET {', '.join(updates)}
                WHERE run_id = ${idx}
            """, *values)

            return result != "UPDATE 0"

    async def list_runs(
        self,
        tenant_id: int,
        site_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[SolverRun]:
        """List solver runs for a tenant."""
        conditions = ["tenant_id = $1"]
        values = [tenant_id]
        idx = 2

        if site_id:
            conditions.append(f"site_id = ${idx}")
            values.append(site_id)
            idx += 1

        if status:
            conditions.append(f"status = ${idx}")
            values.append(status)
            idx += 1

        values.extend([limit, offset])

        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1::text, true)",
                str(tenant_id)
            )

            rows = await conn.fetch(f"""
                SELECT run_id, tenant_id, site_id, status, started_at, completed_at,
                       plan_version_id, solver_type, solver_version, seed,
                       input_hash, matrix_hash, output_hash,
                       kpi_unassigned, kpi_vehicles_used, kpi_coverage_pct,
                       error_code, error_message
                FROM solver_runs
                WHERE {' AND '.join(conditions)}
                ORDER BY started_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}
            """, *values)

            return [
                SolverRun(
                    run_id=str(row["run_id"]),
                    tenant_id=row["tenant_id"],
                    site_id=row["site_id"],
                    status=row["status"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    plan_version_id=row["plan_version_id"],
                    solver_type=row["solver_type"],
                    solver_version=row["solver_version"],
                    seed=row["seed"],
                    input_hash=row["input_hash"],
                    matrix_hash=row["matrix_hash"],
                    output_hash=row["output_hash"],
                    kpi_unassigned=row["kpi_unassigned"],
                    kpi_vehicles_used=row["kpi_vehicles_used"],
                    kpi_coverage_pct=row["kpi_coverage_pct"],
                    error_code=row["error_code"],
                    error_message=row["error_message"],
                )
                for row in rows
            ]


# =============================================================================
# PLAN STATE SERVICE
# =============================================================================

class PlanStateService:
    """
    Service for managing plan state machine.

    States: DRAFT -> SOLVING -> SOLVED -> APPROVED -> PUBLISHED

    Uses transition_plan_state() SQL function for atomic transitions.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def transition_state(
        self,
        plan_version_id: int,
        tenant_id: int,
        transition: PlanStateTransition
    ) -> Dict[str, Any]:
        """Transition plan state."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1::text, true)",
                str(tenant_id)
            )

            result = await conn.fetchval("""
                SELECT transition_plan_state($1, $2, $3, $4, $5)
            """,
                plan_version_id,
                transition.to_state,
                transition.performed_by,
                transition.reason,
                json.dumps(transition.kpi_snapshot) if transition.kpi_snapshot else None
            )

            return json.loads(result) if result else {"success": False, "error": "No result"}

    async def get_plan_state(self, plan_version_id: int, tenant_id: int) -> Optional[Dict]:
        """Get plan with full state info."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1::text, true)",
                str(tenant_id)
            )

            result = await conn.fetchval("""
                SELECT get_plan_with_state($1)
            """, plan_version_id)

            return json.loads(result) if result else None

    async def approve_plan(
        self,
        plan_version_id: int,
        tenant_id: int,
        performed_by: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Approve a solved plan."""
        return await self.transition_state(
            plan_version_id,
            tenant_id,
            PlanStateTransition(
                to_state="APPROVED",
                performed_by=performed_by,
                reason=reason
            )
        )

    async def publish_plan(
        self,
        plan_version_id: int,
        tenant_id: int,
        performed_by: str,
        reason: Optional[str] = None,
        kpi_snapshot: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Publish an approved plan (locks it)."""
        return await self.transition_state(
            plan_version_id,
            tenant_id,
            PlanStateTransition(
                to_state="PUBLISHED",
                performed_by=performed_by,
                reason=reason,
                kpi_snapshot=kpi_snapshot
            )
        )

    async def reject_plan(
        self,
        plan_version_id: int,
        tenant_id: int,
        performed_by: str,
        reason: str
    ) -> Dict[str, Any]:
        """Reject a plan."""
        return await self.transition_state(
            plan_version_id,
            tenant_id,
            PlanStateTransition(
                to_state="REJECTED",
                performed_by=performed_by,
                reason=reason
            )
        )

    async def check_can_modify(self, plan_version_id: int, tenant_id: int) -> bool:
        """Check if plan can be modified."""
        state = await self.get_plan_state(plan_version_id, tenant_id)
        if not state:
            return False
        return state.get("can_modify", False)

    async def check_is_frozen(self, plan_version_id: int, tenant_id: int) -> bool:
        """Check if plan is in freeze window."""
        state = await self.get_plan_state(plan_version_id, tenant_id)
        if not state:
            return False
        return state.get("is_frozen", False)


# =============================================================================
# HASH UTILITIES
# =============================================================================

def compute_input_hash(stops: List[Dict], vehicles: List[Dict], config: Dict) -> str:
    """Compute deterministic hash of solver input."""
    data = {
        "stops": sorted([s.get("id", "") for s in stops]),
        "vehicles": sorted([v.get("id", "") for v in vehicles]),
        "config": config
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def compute_output_hash(routes: Dict, unassigned: List[str]) -> str:
    """Compute deterministic hash of solver output."""
    data = {
        "routes": {k: [s.get("stop_id", "") for s in v.get("stops", [])]
                   for k, v in routes.items()},
        "unassigned": sorted(unassigned)
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
