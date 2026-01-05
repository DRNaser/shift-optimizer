"""
SOLVEREIGN V3.3a API - Plan Repository
======================================

Tenant-scoped plan data access.
"""

from datetime import datetime
from typing import Optional, List

from .base import BaseRepository


class PlanRepository(BaseRepository):
    """Repository for plan_versions, assignments, and audit_log."""

    async def get_by_id(self, plan_id: int) -> Optional[dict]:
        """Get plan by ID."""
        query = """
            SELECT
                id, status, forecast_version_id, seed, output_hash,
                solver_config_hash, created_at, started_at, completed_at,
                locked_at, locked_by, audit_passed_count, audit_failed_count,
                error_message, notes
            FROM plan_versions
            WHERE id = %s AND tenant_id = %s
        """
        return await self._execute(query, (plan_id, self.tenant_id), fetch_one=True)

    async def list_plans(
        self,
        forecast_id: Optional[int] = None,
        status_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[dict], int]:
        """List plans with pagination."""
        offset = (page - 1) * page_size

        where_parts = ["tenant_id = %s"]
        params = [self.tenant_id]

        if forecast_id:
            where_parts.append("forecast_version_id = %s")
            params.append(forecast_id)

        if status_filter:
            where_parts.append("status = %s")
            params.append(status_filter)

        where_clause = " AND ".join(where_parts)

        # Count
        count_result = await self._execute(
            f"SELECT COUNT(*) as total FROM plan_versions WHERE {where_clause}",
            tuple(params),
            fetch_one=True
        )
        total = count_result["total"] if count_result else 0

        # Items
        query = f"""
            SELECT
                id, status, forecast_version_id, seed, output_hash,
                created_at, locked_at, audit_passed_count, audit_failed_count
            FROM plan_versions
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        items = await self._execute(query, tuple(params) + (page_size, offset), fetch_all=True)

        return items or [], total

    async def create(
        self,
        forecast_version_id: int,
        seed: int,
        solver_config_hash: str,
        status: str = "INGESTED",
    ) -> dict:
        """Create new plan version."""
        query = """
            INSERT INTO plan_versions (
                tenant_id, forecast_version_id, seed, solver_config_hash,
                status, output_hash
            )
            VALUES (%s, %s, %s, %s, %s, '')
            RETURNING id, status, forecast_version_id, seed, created_at
        """
        return await self._execute_returning(
            query,
            (self.tenant_id, forecast_version_id, seed, solver_config_hash, status)
        )

    async def update_status(
        self,
        plan_id: int,
        status: str,
        output_hash: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[dict]:
        """Update plan status."""
        set_parts = ["status = %s"]
        params = [status]

        if status == "SOLVING":
            set_parts.append("started_at = NOW()")
            set_parts.append("lock_acquired_at = NOW()")
        elif status in ("SOLVED", "FAILED", "AUDITED", "DRAFT"):
            set_parts.append("completed_at = NOW()")
            set_parts.append("lock_released_at = NOW()")

        if output_hash:
            set_parts.append("output_hash = %s")
            params.append(output_hash)

        if error_message:
            set_parts.append("error_message = %s")
            params.append(error_message)

        params.extend([plan_id, self.tenant_id])

        query = f"""
            UPDATE plan_versions
            SET {", ".join(set_parts)}
            WHERE id = %s AND tenant_id = %s
            RETURNING id, status, output_hash
        """
        return await self._execute_returning(query, tuple(params))

    async def lock_plan(
        self,
        plan_id: int,
        locked_by: str,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        """Lock a plan for release."""
        query = """
            UPDATE plan_versions
            SET status = 'LOCKED', locked_at = NOW(), locked_by = %s, notes = %s
            WHERE id = %s AND tenant_id = %s AND status = 'DRAFT'
            RETURNING id, status, locked_at, locked_by
        """
        return await self._execute_returning(query, (locked_by, notes, plan_id, self.tenant_id))

    async def supersede_previous_locked(self, forecast_id: int, new_plan_id: int) -> int:
        """Mark previous locked plans as superseded."""
        query = """
            UPDATE plan_versions
            SET status = 'SUPERSEDED'
            WHERE forecast_version_id = %s
              AND tenant_id = %s
              AND status = 'LOCKED'
              AND id != %s
        """
        # This would need a custom implementation to return affected rows
        # For now, just execute
        await self._execute(query, (forecast_id, self.tenant_id, new_plan_id))
        return 0  # TODO: Return affected rows

    async def get_assignments(self, plan_id: int) -> List[dict]:
        """Get assignments for plan."""
        query = """
            SELECT
                a.id, a.driver_id, a.tour_instance_id, a.day, a.block_id,
                a.role, a.metadata,
                ti.start_ts, ti.end_ts, ti.duration_min, ti.work_hours
            FROM assignments a
            JOIN tour_instances ti ON a.tour_instance_id = ti.id
            WHERE a.plan_version_id = %s AND a.tenant_id = %s
            ORDER BY a.driver_id, a.day, ti.start_ts
        """
        return await self._execute(query, (plan_id, self.tenant_id), fetch_all=True) or []

    async def get_audit_results(self, plan_id: int) -> List[dict]:
        """Get audit results for plan."""
        query = """
            SELECT check_name, status, count as violation_count, details_json, created_at
            FROM audit_log
            WHERE plan_version_id = %s AND tenant_id = %s
            ORDER BY created_at
        """
        return await self._execute(query, (plan_id, self.tenant_id), fetch_all=True) or []

    async def add_audit_result(
        self,
        plan_id: int,
        check_name: str,
        status: str,
        violation_count: int,
        details: Optional[dict] = None,
    ) -> dict:
        """Add audit result."""
        query = """
            INSERT INTO audit_log (tenant_id, plan_version_id, check_name, status, count, details_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, check_name, status, count
        """
        return await self._execute_returning(
            query,
            (self.tenant_id, plan_id, check_name, status, violation_count, details)
        )

    async def update_audit_counts(self, plan_id: int) -> Optional[dict]:
        """Update plan audit counts from audit_log."""
        query = """
            UPDATE plan_versions pv
            SET
                audit_passed_count = (
                    SELECT COUNT(*) FROM audit_log al
                    WHERE al.plan_version_id = pv.id AND al.status = 'PASS'
                ),
                audit_failed_count = (
                    SELECT COUNT(*) FROM audit_log al
                    WHERE al.plan_version_id = pv.id AND al.status = 'FAIL'
                )
            WHERE pv.id = %s AND pv.tenant_id = %s
            RETURNING id, audit_passed_count, audit_failed_count
        """
        return await self._execute_returning(query, (plan_id, self.tenant_id))
