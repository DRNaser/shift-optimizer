"""
SOLVEREIGN V3.3a API - Forecast Repository
==========================================

Tenant-scoped forecast data access.
"""

from datetime import date
from typing import Optional, List

from .base import BaseRepository


class ForecastRepository(BaseRepository):
    """Repository for forecast_versions and related data."""

    async def get_by_id(self, forecast_id: int) -> Optional[dict]:
        """Get forecast by ID with tour counts."""
        query = """
            SELECT
                fv.id, fv.status, fv.source, fv.input_hash,
                fv.week_anchor_date, fv.created_at, fv.notes,
                fv.parser_config_hash,
                (SELECT COUNT(*) FROM tours_normalized tn WHERE tn.forecast_version_id = fv.id) as tours_count,
                (SELECT COUNT(*) FROM tour_instances ti WHERE ti.forecast_version_id = fv.id) as instances_count
            FROM forecast_versions fv
            WHERE fv.id = %s AND fv.tenant_id = %s
        """
        return await self._execute(query, (forecast_id, self.tenant_id), fetch_one=True)

    async def get_by_input_hash(self, input_hash: str) -> Optional[dict]:
        """Get forecast by input hash (for idempotency)."""
        query = """
            SELECT id, status, source, input_hash, created_at
            FROM forecast_versions
            WHERE input_hash = %s AND tenant_id = %s
        """
        return await self._execute(query, (input_hash, self.tenant_id), fetch_one=True)

    async def list_forecasts(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
    ) -> tuple[List[dict], int]:
        """List forecasts with pagination."""
        offset = (page - 1) * page_size

        where_parts = ["tenant_id = %s"]
        params = [self.tenant_id]

        if status_filter:
            where_parts.append("status = %s")
            params.append(status_filter)

        where_clause = " AND ".join(where_parts)

        # Get total count
        count_query = f"SELECT COUNT(*) as total FROM forecast_versions WHERE {where_clause}"
        count_result = await self._execute(count_query, tuple(params), fetch_one=True)
        total = count_result["total"] if count_result else 0

        # Get items
        query = f"""
            SELECT
                fv.id, fv.status, fv.source, fv.created_at,
                (SELECT COUNT(*) FROM tours_normalized WHERE forecast_version_id = fv.id) as tours_count,
                EXISTS(
                    SELECT 1 FROM plan_versions pv
                    WHERE pv.forecast_version_id = fv.id AND pv.status = 'LOCKED'
                ) as has_locked_plan
            FROM forecast_versions fv
            WHERE {where_clause}
            ORDER BY fv.created_at DESC
            LIMIT %s OFFSET %s
        """
        items = await self._execute(query, tuple(params) + (page_size, offset), fetch_all=True)

        return items or [], total

    async def create(
        self,
        source: str,
        input_hash: str,
        parser_config_hash: str,
        status: str,
        week_anchor_date: Optional[date] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Create new forecast version."""
        query = """
            INSERT INTO forecast_versions (
                tenant_id, source, input_hash, parser_config_hash,
                status, week_anchor_date, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, status, source, input_hash, created_at
        """
        return await self._execute_returning(
            query,
            (self.tenant_id, source, input_hash, parser_config_hash, status, week_anchor_date, notes)
        )

    async def get_tours_raw(self, forecast_id: int) -> List[dict]:
        """Get raw tour lines for forecast."""
        query = """
            SELECT id, line_no, raw_text, parse_status, parse_errors, parse_warnings, canonical_text
            FROM tours_raw
            WHERE forecast_version_id = %s AND tenant_id = %s
            ORDER BY line_no
        """
        return await self._execute(query, (forecast_id, self.tenant_id), fetch_all=True) or []

    async def get_tours_normalized(self, forecast_id: int) -> List[dict]:
        """Get normalized tours for forecast."""
        query = """
            SELECT
                id, day, start_ts, end_ts, duration_min, work_hours,
                span_group_key, tour_fingerprint, count, depot, skill
            FROM tours_normalized
            WHERE forecast_version_id = %s AND tenant_id = %s
            ORDER BY day, start_ts
        """
        return await self._execute(query, (forecast_id, self.tenant_id), fetch_all=True) or []

    async def get_tour_instances(self, forecast_id: int) -> List[dict]:
        """Get expanded tour instances for forecast."""
        query = """
            SELECT
                id, tour_template_id, instance_no, day, start_ts, end_ts,
                crosses_midnight, duration_min, work_hours, depot, skill
            FROM tour_instances
            WHERE forecast_version_id = %s AND tenant_id = %s
            ORDER BY day, start_ts, instance_no
        """
        return await self._execute(query, (forecast_id, self.tenant_id), fetch_all=True) or []
