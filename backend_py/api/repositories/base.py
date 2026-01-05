"""
SOLVEREIGN V3.3a API - Base Repository
======================================

Base class for tenant-scoped repositories.
"""

from typing import Optional, List, Any

import psycopg
from psycopg.rows import dict_row

from ..database import DatabaseManager


class BaseRepository:
    """
    Base repository with tenant isolation.

    All queries automatically include tenant_id filtering.
    """

    def __init__(self, db: DatabaseManager, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id

    async def _execute(
        self,
        query: str,
        params: tuple = (),
        fetch_one: bool = False,
        fetch_all: bool = False,
    ) -> Any:
        """
        Execute query with tenant isolation.

        Automatically prepends tenant_id to params if query contains %s for tenant.
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)

                if fetch_one:
                    return await cur.fetchone()
                if fetch_all:
                    return await cur.fetchall()

                return None

    async def _execute_returning(
        self,
        query: str,
        params: tuple = (),
    ) -> Optional[dict]:
        """Execute INSERT/UPDATE with RETURNING clause."""
        async with self.db.transaction() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

    async def _count(self, table: str, where: str = "", params: tuple = ()) -> int:
        """Count rows in table with tenant isolation."""
        query = f"SELECT COUNT(*) as count FROM {table} WHERE tenant_id = %s"
        if where:
            query += f" AND {where}"

        result = await self._execute(query, (self.tenant_id,) + params, fetch_one=True)
        return result["count"] if result else 0

    async def _exists(self, table: str, id_column: str, id_value: int) -> bool:
        """Check if record exists for tenant."""
        query = f"SELECT 1 FROM {table} WHERE {id_column} = %s AND tenant_id = %s"
        result = await self._execute(query, (id_value, self.tenant_id), fetch_one=True)
        return result is not None
