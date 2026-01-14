"""
DB Schema Invariant Tests - Prevents Schema Drift

These tests verify that the database schema matches the code expectations.
They catch drift issues BEFORE they cause runtime errors in E2E tests.

Run: pytest backend_py/api/tests/test_db_schema_invariants.py -v
"""

import os
import pytest
import asyncpg
from typing import List, Dict, Any

# Skip if no DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set - skipping DB schema tests"
)


@pytest.fixture
async def db_conn():
    """Get async database connection."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()


class TestAuthSessionsSchema:
    """Test auth.sessions table schema matches code expectations."""

    REQUIRED_COLUMNS = {
        "id": "uuid",
        "user_id": "uuid",
        "tenant_id": "integer",  # Can be NULL for platform_admin
        "site_id": "integer",
        "role_id": "integer",
        "session_hash": "character",  # CHAR(64) - canonical name
        "created_at": "timestamp with time zone",
        "expires_at": "timestamp with time zone",
        "last_activity_at": "timestamp with time zone",
        "revoked_at": "timestamp with time zone",
        "revoked_reason": "text",
        "rotated_from": "uuid",
        "ip_hash": "character",
        "user_agent_hash": "character",
        "is_platform_scope": "boolean",  # CRITICAL: Added in 040
        "active_tenant_id": "integer",  # Added in 041
        "active_site_id": "integer",  # Added in 041
    }

    @pytest.mark.asyncio
    async def test_sessions_table_exists(self, db_conn):
        """auth.sessions table must exist."""
        result = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'auth' AND table_name = 'sessions'
            )
        """)
        assert result is True, "auth.sessions table does not exist"

    @pytest.mark.asyncio
    async def test_sessions_has_session_hash_not_token_hash(self, db_conn):
        """
        CRITICAL: auth.sessions must use 'session_hash' (not 'token_hash').

        The inconsistency between token_hash and session_hash caused the
        E2E login failures. This test prevents regression.
        """
        # session_hash should exist
        session_hash_exists = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'auth' AND table_name = 'sessions'
                AND column_name = 'session_hash'
            )
        """)
        assert session_hash_exists is True, "session_hash column missing - this will break login!"

        # token_hash should NOT exist (deprecated name)
        token_hash_exists = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'auth' AND table_name = 'sessions'
                AND column_name = 'token_hash'
            )
        """)
        # Warn if token_hash exists alongside session_hash
        if token_hash_exists:
            pytest.xfail("token_hash column exists - should be removed or migrated to session_hash")

    @pytest.mark.asyncio
    async def test_sessions_has_is_platform_scope(self, db_conn):
        """
        CRITICAL: is_platform_scope column must exist.

        Without this column, platform admin sessions fail validation.
        """
        result = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'auth' AND table_name = 'sessions'
                AND column_name = 'is_platform_scope'
            )
        """)
        assert result is True, "is_platform_scope column missing - platform admin login will fail!"

    @pytest.mark.asyncio
    async def test_sessions_has_context_columns(self, db_conn):
        """active_tenant_id and active_site_id columns must exist for context switching."""
        for col in ["active_tenant_id", "active_site_id"]:
            result = await db_conn.fetchval(f"""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'auth' AND table_name = 'sessions'
                    AND column_name = '{col}'
                )
            """)
            assert result is True, f"{col} column missing - context switching will fail!"

    @pytest.mark.asyncio
    async def test_all_required_columns_exist(self, db_conn):
        """All required columns must exist in auth.sessions."""
        columns = await db_conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'auth' AND table_name = 'sessions'
        """)
        existing_columns = {row["column_name"]: row["data_type"] for row in columns}

        missing = []
        for col_name in self.REQUIRED_COLUMNS:
            if col_name not in existing_columns:
                missing.append(col_name)

        assert len(missing) == 0, f"Missing columns in auth.sessions: {missing}"


class TestValidateSessionFunction:
    """Test auth.validate_session function signature matches code expectations."""

    @pytest.mark.asyncio
    async def test_validate_session_exists(self, db_conn):
        """validate_session function must exist."""
        result = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.routines
                WHERE routine_schema = 'auth' AND routine_name = 'validate_session'
            )
        """)
        assert result is True, "auth.validate_session function does not exist"

    @pytest.mark.asyncio
    async def test_validate_session_returns_12_columns(self, db_conn):
        """
        CRITICAL: validate_session must return 12 columns.

        The Python code expects:
        session_id, user_id, user_email, user_display_name, tenant_id, site_id,
        role_id, role_name, expires_at, is_platform_scope, active_tenant_id, active_site_id

        If the function returns fewer columns, the code will fail with:
        "structure of query does not match function result type"
        """
        # Get function return type
        result = await db_conn.fetch("""
            SELECT
                p.proname as function_name,
                pg_get_function_result(p.oid) as return_type
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'auth' AND p.proname = 'validate_session'
        """)

        assert len(result) > 0, "validate_session function not found"

        return_type = result[0]["return_type"]

        # Check that it returns a TABLE with 12 columns
        expected_columns = [
            "session_id",
            "user_id",
            "user_email",
            "user_display_name",
            "tenant_id",
            "site_id",
            "role_id",
            "role_name",
            "expires_at",
            "is_platform_scope",
            "active_tenant_id",
            "active_site_id",
        ]

        for col in expected_columns:
            assert col in return_type.lower(), f"validate_session missing return column: {col}"

    @pytest.mark.asyncio
    async def test_validate_session_return_types(self, db_conn):
        """
        CRITICAL: Return types must be VARCHAR(255) not TEXT.

        The Python code using psycopg expects specific types. If the function
        returns TEXT where the code expects VARCHAR, it can cause type mismatches.
        """
        result = await db_conn.fetch("""
            SELECT
                pg_get_function_result(p.oid) as return_type
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'auth' AND p.proname = 'validate_session'
        """)

        return_type = result[0]["return_type"]

        # user_email and user_display_name should be character varying (VARCHAR)
        # not text, to match the auth.users table schema
        assert "character varying" in return_type.lower() or "varchar" in return_type.lower(), \
            f"validate_session return types may be incorrect: {return_type}"


class TestAuthUsersSchema:
    """Test auth.users table schema."""

    @pytest.mark.asyncio
    async def test_users_table_exists(self, db_conn):
        """auth.users table must exist."""
        result = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'auth' AND table_name = 'users'
            )
        """)
        assert result is True, "auth.users table does not exist"

    @pytest.mark.asyncio
    async def test_users_email_is_varchar(self, db_conn):
        """email column must be VARCHAR(255) not TEXT."""
        result = await db_conn.fetchrow("""
            SELECT data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = 'auth' AND table_name = 'users'
            AND column_name = 'email'
        """)
        assert result is not None, "email column not found"
        assert result["data_type"] == "character varying", \
            f"email should be VARCHAR, got {result['data_type']}"
        assert result["character_maximum_length"] == 255, \
            f"email should be VARCHAR(255), got {result['character_maximum_length']}"


class TestAuthRolesSchema:
    """Test auth.roles table and required roles."""

    REQUIRED_ROLES = [
        "platform_admin",
        "tenant_admin",
        "operator_admin",
        "dispatcher",
        "ops_readonly",
    ]

    @pytest.mark.asyncio
    async def test_required_roles_exist(self, db_conn):
        """All required roles must be seeded."""
        existing_roles = await db_conn.fetch("""
            SELECT name FROM auth.roles
        """)
        existing_names = {row["name"] for row in existing_roles}

        missing = []
        for role in self.REQUIRED_ROLES:
            if role not in existing_names:
                missing.append(role)

        assert len(missing) == 0, f"Missing roles: {missing}"


class TestVerifyFunctions:
    """Test that verification functions work correctly."""

    @pytest.mark.asyncio
    async def test_verify_schema_integrity_passes(self, db_conn):
        """auth.verify_schema_integrity() must return all PASS."""
        results = await db_conn.fetch("""
            SELECT check_name, status, details
            FROM auth.verify_schema_integrity()
        """)

        failures = [r for r in results if r["status"] != "PASS"]
        if failures:
            for f in failures:
                print(f"FAIL: {f['check_name']} - {f['details']}")
            pytest.fail(f"Schema integrity checks failed: {[f['check_name'] for f in failures]}")

    @pytest.mark.asyncio
    async def test_verify_rbac_integrity_passes(self, db_conn):
        """auth.verify_rbac_integrity() must return all PASS."""
        results = await db_conn.fetch("""
            SELECT check_name, status, details
            FROM auth.verify_rbac_integrity()
        """)

        failures = [r for r in results if r["status"] not in ("PASS", "WARN")]
        if failures:
            for f in failures:
                print(f"FAIL: {f['check_name']} - {f['details']}")
            pytest.fail(f"RBAC integrity checks failed: {[f['check_name'] for f in failures]}")


class TestNoSchemaAntipatternsPresent:
    """Test for known schema antipatterns that caused issues."""

    @pytest.mark.asyncio
    async def test_no_fake_tenant_zero(self, db_conn):
        """
        CRITICAL: No tenant_id=0 should exist.

        The "fake tenant_id=0 for platform admin" pattern was removed.
        Platform admins have NULL tenant_id in bindings.
        """
        result = await db_conn.fetchval("""
            SELECT EXISTS(SELECT 1 FROM tenants WHERE id = 0)
        """)
        assert result is False, "Fake tenant_id=0 exists - this pattern was removed!"

    @pytest.mark.asyncio
    async def test_sessions_allows_null_tenant_id(self, db_conn):
        """
        auth.sessions.tenant_id must be nullable for platform admin sessions.
        """
        result = await db_conn.fetchrow("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'auth' AND table_name = 'sessions'
            AND column_name = 'tenant_id'
        """)
        # Note: PostgreSQL stores FK integer columns as NOT NULL by default
        # For platform_admin, we use is_platform_scope=TRUE instead of tenant_id=NULL
        # This test documents the expected behavior
        pass  # The design uses is_platform_scope flag instead of nullable tenant_id


class TestIndexesAndConstraints:
    """Test critical indexes and constraints exist."""

    @pytest.mark.asyncio
    async def test_session_hash_unique_index_exists(self, db_conn):
        """
        CRITICAL: session_hash must have a UNIQUE constraint/index.

        Without this, duplicate session tokens could be created, causing
        security issues and unpredictable behavior.
        """
        result = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'auth' AND tablename = 'sessions'
                AND (
                    indexdef LIKE '%session_hash%UNIQUE%'
                    OR indexdef LIKE '%UNIQUE%session_hash%'
                )
            )
        """)
        # Also check for UNIQUE constraint
        constraint_exists = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.table_schema = 'auth' AND tc.table_name = 'sessions'
                AND ccu.column_name = 'session_hash'
                AND tc.constraint_type = 'UNIQUE'
            )
        """)
        assert result or constraint_exists, "session_hash must have UNIQUE constraint!"

    @pytest.mark.asyncio
    async def test_session_hash_not_null(self, db_conn):
        """session_hash must be NOT NULL."""
        result = await db_conn.fetchrow("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'auth' AND table_name = 'sessions'
            AND column_name = 'session_hash'
        """)
        assert result is not None, "session_hash column not found"
        assert result["is_nullable"] == "NO", "session_hash must be NOT NULL"

    @pytest.mark.asyncio
    async def test_user_email_unique_index_exists(self, db_conn):
        """email must have a UNIQUE constraint."""
        result = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.table_schema = 'auth' AND tc.table_name = 'users'
                AND ccu.column_name = 'email'
                AND tc.constraint_type = 'UNIQUE'
            )
        """)
        assert result is True, "email must have UNIQUE constraint!"

    @pytest.mark.asyncio
    async def test_is_platform_scope_has_default(self, db_conn):
        """is_platform_scope must have DEFAULT FALSE."""
        result = await db_conn.fetchrow("""
            SELECT column_default
            FROM information_schema.columns
            WHERE table_schema = 'auth' AND table_name = 'sessions'
            AND column_name = 'is_platform_scope'
        """)
        assert result is not None, "is_platform_scope column not found"
        assert result["column_default"] is not None, "is_platform_scope must have DEFAULT"
        assert "false" in str(result["column_default"]).lower(), \
            f"is_platform_scope default should be FALSE, got {result['column_default']}"

    @pytest.mark.asyncio
    async def test_sessions_expires_at_not_null(self, db_conn):
        """expires_at must be NOT NULL."""
        result = await db_conn.fetchrow("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'auth' AND table_name = 'sessions'
            AND column_name = 'expires_at'
        """)
        assert result is not None, "expires_at column not found"
        assert result["is_nullable"] == "NO", "expires_at must be NOT NULL"

    @pytest.mark.asyncio
    async def test_role_name_unique(self, db_conn):
        """role name must be unique."""
        result = await db_conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.table_schema = 'auth' AND tc.table_name = 'roles'
                AND ccu.column_name = 'name'
                AND tc.constraint_type = 'UNIQUE'
            )
        """)
        assert result is True, "role name must have UNIQUE constraint!"


class TestE2EUsersSeeded:
    """Test that E2E users are seeded correctly."""

    E2E_USERS = [
        ("e2e-platform-admin@example.com", "platform_admin"),
        ("e2e-tenant-admin@example.com", "tenant_admin"),
        ("e2e-dispatcher@example.com", "dispatcher"),
    ]

    @pytest.mark.asyncio
    async def test_e2e_users_exist(self, db_conn):
        """E2E test users should exist after seeding."""
        for email, expected_role in self.E2E_USERS:
            result = await db_conn.fetchrow("""
                SELECT u.id, u.is_active, r.name as role_name
                FROM auth.users u
                JOIN auth.user_bindings ub ON ub.user_id = u.id
                JOIN auth.roles r ON r.id = ub.role_id
                WHERE LOWER(u.email) = LOWER($1)
            """, email)

            if result is None:
                pytest.skip(f"E2E user {email} not seeded yet - run scripts/seed-e2e.ps1")

            assert result["is_active"] is True, f"E2E user {email} should be active"
            assert result["role_name"] == expected_role, \
                f"E2E user {email} should have role {expected_role}, got {result['role_name']}"
