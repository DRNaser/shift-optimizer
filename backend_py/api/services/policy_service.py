"""
Policy Service (Kernel)

Core service for managing policy profiles and tenant pack configurations.
This is a KERNEL service used by all packs to retrieve their configuration.

See ADR-002: Policy Profiles for architecture details.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Union
from enum import Enum


class PolicyStatus(str, Enum):
    """Policy profile status."""
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass
class ActivePolicy:
    """
    Result when an active policy is found.

    Attributes:
        profile_id: UUID of the policy profile
        config: Configuration dictionary
        config_hash: SHA256 hash for determinism verification
        schema_version: Schema version of the config
    """
    profile_id: str
    config: Dict[str, Any]
    config_hash: str
    schema_version: str


@dataclass
class PolicyNotFound:
    """
    Result when no policy is configured.

    Attributes:
        reason: Why no policy was found
        use_defaults: Whether to use pack defaults
    """
    reason: str
    use_defaults: bool = True


@dataclass
class PolicyProfile:
    """Full policy profile data."""
    id: str
    tenant_id: str
    pack_id: str
    name: str
    description: Optional[str]
    version: int
    status: PolicyStatus
    config_json: Dict[str, Any]
    config_hash: str
    schema_version: str
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


class PolicyService:
    """
    Core service for policy profile management.

    Usage:
        policy_service = PolicyService(db_pool)
        policy = await policy_service.get_active_policy("tenant-uuid", "roster")

        if isinstance(policy, ActivePolicy):
            config = policy.config
            config_hash = policy.config_hash
        else:
            # Use pack defaults
            config = DEFAULT_CONFIG
    """

    def __init__(self, db_pool):
        """
        Initialize policy service.

        Args:
            db_pool: Database connection pool (psycopg3 AsyncConnectionPool)
        """
        self.db_pool = db_pool
        self._schema_validators = {}

    def register_schema_validator(self, pack_id: str, validator_fn):
        """
        Register a schema validator for a pack.

        Args:
            pack_id: Pack identifier (e.g., "roster", "routing")
            validator_fn: Function that takes config dict and raises on invalid
        """
        self._schema_validators[pack_id] = validator_fn

    async def get_active_policy(
        self,
        tenant_id: str,
        pack_id: str,
        site_id: Optional[str] = None
    ) -> Union[ActivePolicy, PolicyNotFound]:
        """
        Get active policy for a tenant/pack.

        Args:
            tenant_id: UUID of the tenant
            pack_id: Pack identifier (e.g., "roster", "routing")
            site_id: Optional site UUID (for future site-specific policies)

        Returns:
            ActivePolicy if found, PolicyNotFound if no profile configured.
        """
        async with self.db_pool.connection() as conn:
            # Use the helper function defined in migration
            row = await conn.fetchone("""
                SELECT
                    profile_id,
                    config_json,
                    config_hash,
                    schema_version,
                    use_defaults
                FROM core.get_active_policy($1, $2)
            """, (tenant_id, pack_id))

            if not row or row['use_defaults'] or row['profile_id'] is None:
                return PolicyNotFound(
                    reason=f"No active policy for tenant {tenant_id}, pack {pack_id}",
                    use_defaults=True
                )

            return ActivePolicy(
                profile_id=str(row['profile_id']),
                config=row['config_json'],
                config_hash=row['config_hash'],
                schema_version=row['schema_version']
            )

    async def list_profiles(
        self,
        tenant_id: str,
        pack_id: Optional[str] = None,
        status: Optional[PolicyStatus] = None
    ) -> list[PolicyProfile]:
        """
        List policy profiles for a tenant.

        Args:
            tenant_id: UUID of the tenant
            pack_id: Optional filter by pack
            status: Optional filter by status

        Returns:
            List of PolicyProfile objects
        """
        query = """
            SELECT id, tenant_id, pack_id, name, description, version, status,
                   config_json, config_hash, schema_version,
                   created_at, created_by, updated_at, updated_by
            FROM core.policy_profiles
            WHERE tenant_id = $1
        """
        params = [tenant_id]

        if pack_id:
            query += " AND pack_id = $2"
            params.append(pack_id)

        if status:
            query += f" AND status = ${len(params) + 1}"
            params.append(status.value)

        query += " ORDER BY pack_id, name, version DESC"

        async with self.db_pool.connection() as conn:
            rows = await conn.fetchall(query, params)
            return [self._row_to_profile(row) for row in rows]

    async def create_profile(
        self,
        tenant_id: str,
        pack_id: str,
        name: str,
        config: Dict[str, Any],
        created_by: str,
        description: Optional[str] = None,
        schema_version: str = "1.0"
    ) -> str:
        """
        Create a new policy profile (draft status).

        Args:
            tenant_id: UUID of the tenant
            pack_id: Pack identifier
            name: Profile name
            config: Configuration dictionary
            created_by: User who created the profile
            description: Optional description
            schema_version: Schema version (default "1.0")

        Returns:
            UUID of created profile

        Raises:
            ValueError: If config is invalid for the pack schema
        """
        # Validate config against pack schema
        self._validate_config(pack_id, config, schema_version)

        async with self.db_pool.connection() as conn:
            row = await conn.fetchone("""
                INSERT INTO core.policy_profiles
                    (tenant_id, pack_id, name, description, config_json, schema_version,
                     created_by, updated_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                RETURNING id
            """, (tenant_id, pack_id, name, description,
                  json.dumps(config), schema_version, created_by))
            return str(row['id'])

    async def update_profile(
        self,
        profile_id: str,
        config: Dict[str, Any],
        updated_by: str,
        description: Optional[str] = None
    ) -> None:
        """
        Update a profile's configuration (creates new version).

        Args:
            profile_id: UUID of the profile
            config: New configuration dictionary
            updated_by: User who updated the profile
            description: Optional new description
        """
        async with self.db_pool.connection() as conn:
            # Get current profile
            current = await conn.fetchone("""
                SELECT pack_id, schema_version FROM core.policy_profiles WHERE id = $1
            """, (profile_id,))

            if not current:
                raise ValueError(f"Profile {profile_id} not found")

            # Validate new config
            self._validate_config(
                current['pack_id'],
                config,
                current['schema_version']
            )

            # Update
            update_fields = ["config_json = $2", "updated_at = NOW()", "updated_by = $3"]
            params = [profile_id, json.dumps(config), updated_by]

            if description is not None:
                update_fields.append(f"description = ${len(params) + 1}")
                params.append(description)

            await conn.execute(f"""
                UPDATE core.policy_profiles
                SET {', '.join(update_fields)}
                WHERE id = $1
            """, params)

    async def activate_profile(
        self,
        profile_id: str,
        activated_by: str
    ) -> None:
        """
        Activate a profile (archives previous active with same name).

        Args:
            profile_id: UUID of the profile to activate
            activated_by: User who activated the profile
        """
        async with self.db_pool.connection() as conn:
            await conn.execute("""
                UPDATE core.policy_profiles
                SET status = 'active', updated_at = NOW(), updated_by = $2
                WHERE id = $1
            """, (profile_id, activated_by))

    async def archive_profile(
        self,
        profile_id: str,
        archived_by: str
    ) -> None:
        """
        Archive a profile.

        Args:
            profile_id: UUID of the profile to archive
            archived_by: User who archived the profile
        """
        async with self.db_pool.connection() as conn:
            await conn.execute("""
                UPDATE core.policy_profiles
                SET status = 'archived', updated_at = NOW(), updated_by = $2
                WHERE id = $1
            """, (profile_id, archived_by))

    async def set_active_profile(
        self,
        tenant_id: str,
        pack_id: str,
        profile_id: Optional[str],
        updated_by: str
    ) -> None:
        """
        Set the active profile for a tenant/pack.

        Args:
            tenant_id: UUID of the tenant
            pack_id: Pack identifier
            profile_id: UUID of the profile (None to use pack defaults)
            updated_by: User who updated the setting
        """
        async with self.db_pool.connection() as conn:
            if profile_id:
                await conn.execute("""
                    INSERT INTO core.tenant_pack_settings
                        (tenant_id, pack_id, active_profile_id, use_pack_defaults, updated_by)
                    VALUES ($1, $2, $3, false, $4)
                    ON CONFLICT (tenant_id, pack_id) DO UPDATE SET
                        active_profile_id = $3,
                        use_pack_defaults = false,
                        updated_at = NOW(),
                        updated_by = $4
                """, (tenant_id, pack_id, profile_id, updated_by))
            else:
                # Reset to pack defaults
                await conn.execute("""
                    INSERT INTO core.tenant_pack_settings
                        (tenant_id, pack_id, active_profile_id, use_pack_defaults, updated_by)
                    VALUES ($1, $2, NULL, true, $3)
                    ON CONFLICT (tenant_id, pack_id) DO UPDATE SET
                        active_profile_id = NULL,
                        use_pack_defaults = true,
                        updated_at = NOW(),
                        updated_by = $3
                """, (tenant_id, pack_id, updated_by))

    def _validate_config(
        self,
        pack_id: str,
        config: Dict[str, Any],
        schema_version: str
    ) -> None:
        """
        Validate config against pack-specific schema.

        Raises:
            ValueError: If config is invalid
        """
        # Check if we have a registered validator
        if pack_id in self._schema_validators:
            self._schema_validators[pack_id](config)
            return

        # Fallback: Try to import pack schema
        try:
            if pack_id == "roster":
                from ...packs.roster.config_schema import validate_roster_config
                validate_roster_config(config)
            elif pack_id == "routing":
                from ...packs.routing.config_schema import RoutingPolicyConfig
                RoutingPolicyConfig(**config)
            else:
                # Unknown pack - allow any config (no validation)
                pass
        except ImportError:
            # Pack schema not available - skip validation
            pass

    def _row_to_profile(self, row) -> PolicyProfile:
        """Convert database row to PolicyProfile object."""
        return PolicyProfile(
            id=str(row['id']),
            tenant_id=str(row['tenant_id']),
            pack_id=row['pack_id'],
            name=row['name'],
            description=row['description'],
            version=row['version'],
            status=PolicyStatus(row['status']),
            config_json=row['config_json'],
            config_hash=row['config_hash'],
            schema_version=row['schema_version'],
            created_at=row['created_at'],
            created_by=row['created_by'],
            updated_at=row['updated_at'],
            updated_by=row['updated_by']
        )

    @staticmethod
    def compute_config_hash(config: Dict[str, Any]) -> str:
        """
        Compute SHA256 hash of configuration for determinism verification.

        Args:
            config: Configuration dictionary

        Returns:
            Hex-encoded SHA256 hash
        """
        canonical = json.dumps(config, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode()).hexdigest()


# === DEPENDENCY INJECTION ===

_policy_service_instance: Optional[PolicyService] = None


def get_policy_service() -> PolicyService:
    """
    Get the global PolicyService instance.

    Returns:
        PolicyService instance

    Raises:
        RuntimeError: If service not initialized
    """
    if _policy_service_instance is None:
        raise RuntimeError("PolicyService not initialized. Call init_policy_service() first.")
    return _policy_service_instance


def get_policy_service_or_none() -> Optional[PolicyService]:
    """
    Get the global PolicyService instance, or None if not initialized.

    Use this in contexts where PolicyService might not be available
    (e.g., Celery workers, CLI scripts).

    Returns:
        PolicyService instance or None
    """
    return _policy_service_instance


def init_policy_service(db_pool) -> PolicyService:
    """
    Initialize the global PolicyService instance.

    Args:
        db_pool: Database connection pool

    Returns:
        Initialized PolicyService instance
    """
    global _policy_service_instance
    _policy_service_instance = PolicyService(db_pool)
    return _policy_service_instance


def create_policy_service_for_worker(connection_string: str = None) -> PolicyService:
    """
    Create a standalone PolicyService for worker/CLI contexts.

    This creates a new service with its own connection pool, suitable
    for Celery workers or CLI scripts that don't have access to the
    FastAPI app state.

    Args:
        connection_string: Database connection string. If None, reads from
                          environment (DATABASE_URL or individual DB_* vars).

    Returns:
        PolicyService instance (not registered globally)

    Example:
        # In Celery task
        policy_service = create_policy_service_for_worker()
        result = await policy_service.get_active_policy(tenant_id, pack_id)
    """
    import os

    if connection_string is None:
        # Try DATABASE_URL first, then construct from parts
        connection_string = os.environ.get("DATABASE_URL")
        if not connection_string:
            host = os.environ.get("DB_HOST", "localhost")
            port = os.environ.get("DB_PORT", "5432")
            name = os.environ.get("DB_NAME", "solvereign")
            user = os.environ.get("DB_USER", "solvereign")
            password = os.environ.get("DB_PASSWORD", "")
            connection_string = f"postgresql://{user}:{password}@{host}:{port}/{name}"

    # Create a minimal pool-like object for sync usage
    # This is a lightweight wrapper that creates connections on-demand
    class SyncConnectionWrapper:
        def __init__(self, conn_string):
            self.conn_string = conn_string

        def connection(self):
            """Return a context manager for sync connections."""
            import psycopg
            from psycopg.rows import dict_row
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def get_conn():
                conn = psycopg.connect(self.conn_string, row_factory=dict_row)
                try:
                    # Wrap sync connection methods to look async
                    class AsyncWrapper:
                        def __init__(self, sync_conn):
                            self._conn = sync_conn

                        async def fetchone(self, query, params=None):
                            with self._conn.cursor() as cur:
                                cur.execute(query, params or ())
                                return cur.fetchone()

                        async def fetchall(self, query, params=None):
                            with self._conn.cursor() as cur:
                                cur.execute(query, params or ())
                                return cur.fetchall()

                        async def execute(self, query, params=None):
                            with self._conn.cursor() as cur:
                                cur.execute(query, params or ())
                            self._conn.commit()

                    yield AsyncWrapper(conn)
                finally:
                    conn.close()

            return get_conn()

    pool = SyncConnectionWrapper(connection_string)
    return PolicyService(pool)
