"""
SOLVEREIGN V3.3a API - Tenant Repository
========================================

Tenant management (admin operations).
"""

import hashlib
import secrets
from typing import Optional, List

from ..database import DatabaseManager


class TenantRepository:
    """Repository for tenants table (not tenant-scoped - admin only)."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure API key."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """Hash API key for storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def get_by_id(self, tenant_id: int) -> Optional[dict]:
        """Get tenant by ID."""
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, name, is_active, metadata, created_at FROM tenants WHERE id = %s",
                    (tenant_id,)
                )
                return await cur.fetchone()

    async def get_by_api_key(self, api_key: str) -> Optional[dict]:
        """Get tenant by API key."""
        api_key_hash = self.hash_api_key(api_key)
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, name, is_active, metadata, created_at FROM tenants WHERE api_key_hash = %s",
                    (api_key_hash,)
                )
                return await cur.fetchone()

    async def list_tenants(
        self,
        include_inactive: bool = False,
    ) -> List[dict]:
        """List all tenants."""
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                query = "SELECT id, name, is_active, metadata, created_at FROM tenants"
                if not include_inactive:
                    query += " WHERE is_active = TRUE"
                query += " ORDER BY created_at"

                await cur.execute(query)
                return await cur.fetchall() or []

    async def create(
        self,
        name: str,
        metadata: Optional[dict] = None,
    ) -> tuple[dict, str]:
        """
        Create new tenant.

        Returns:
            Tuple of (tenant dict, plaintext API key)
            The API key is only returned once at creation.
        """
        api_key = self.generate_api_key()
        api_key_hash = self.hash_api_key(api_key)

        async with self.db.transaction() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO tenants (name, api_key_hash, is_active, metadata)
                    VALUES (%s, %s, TRUE, %s)
                    RETURNING id, name, is_active, created_at
                    """,
                    (name, api_key_hash, metadata)
                )
                tenant = await cur.fetchone()

        return tenant, api_key

    async def deactivate(self, tenant_id: int) -> Optional[dict]:
        """Deactivate a tenant."""
        async with self.db.transaction() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE tenants
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, is_active
                    """,
                    (tenant_id,)
                )
                return await cur.fetchone()

    async def rotate_api_key(self, tenant_id: int) -> Optional[tuple[dict, str]]:
        """
        Rotate API key for tenant.

        Returns:
            Tuple of (tenant dict, new plaintext API key)
        """
        api_key = self.generate_api_key()
        api_key_hash = self.hash_api_key(api_key)

        async with self.db.transaction() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE tenants
                    SET api_key_hash = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, is_active
                    """,
                    (api_key_hash, tenant_id)
                )
                tenant = await cur.fetchone()

        if tenant:
            return tenant, api_key
        return None

    async def get_stats(self, tenant_id: int) -> dict:
        """Get usage statistics for tenant."""
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM forecast_versions WHERE tenant_id = %s) as forecasts_count,
                        (SELECT COUNT(*) FROM plan_versions WHERE tenant_id = %s) as plans_count,
                        (SELECT COUNT(*) FROM plan_versions WHERE tenant_id = %s AND status = 'LOCKED') as locked_plans_count,
                        (SELECT COUNT(*) FROM assignments WHERE tenant_id = %s) as assignments_count,
                        (SELECT MAX(created_at) FROM forecast_versions WHERE tenant_id = %s) as last_forecast_at,
                        (SELECT MAX(created_at) FROM plan_versions WHERE tenant_id = %s) as last_plan_at
                    """,
                    (tenant_id, tenant_id, tenant_id, tenant_id, tenant_id, tenant_id)
                )
                return await cur.fetchone() or {}
