#!/usr/bin/env python3
"""
SOLVEREIGN - E2E Test Data Seeder
=================================

Creates the minimum data required for E2E tests:
- Test tenant (id=1, code='e2e-test')
- Test site (id=1)
- Test user (platform_admin role)

IDEMPOTENT: Safe to run multiple times.

Environment:
    DATABASE_URL - PostgreSQL connection string
    E2E_TEST_EMAIL - Test user email (default: e2e-test@example.com)
    E2E_TEST_PASSWORD - Test user password (default: E2ETestPassword123!)
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows console fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def get_connection():
    """Get database connection."""
    import psycopg

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    return psycopg.connect(database_url)


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    try:
        from backend_py.api.security.internal_rbac import hash_password as _hash
        return _hash(password)
    except ImportError:
        # Fallback: use argon2-cffi directly
        from argon2 import PasswordHasher
        ph = PasswordHasher()
        return ph.hash(password)


# =============================================================================
# E2E TEST USERS - DETERMINISTIC SEED
# =============================================================================
# These users are created with deterministic IDs for stable E2E tests.
# The password is the same for all users to simplify testing.

E2E_TEST_USERS = [
    {
        "id": "e2e00001-0000-0000-0000-000000000001",
        "email": "e2e-platform-admin@example.com",
        "display_name": "E2E Platform Admin",
        "role": "platform_admin",
        "tenant_id": None,  # Platform admin has no tenant binding
        "site_id": None,
    },
    {
        "id": "e2e00002-0000-0000-0000-000000000002",
        "email": "e2e-tenant-admin@example.com",
        "display_name": "E2E Tenant Admin",
        "role": "tenant_admin",
        "tenant_id": 1,
        "site_id": None,  # All sites in tenant
    },
    {
        "id": "e2e00003-0000-0000-0000-000000000003",
        "email": "e2e-dispatcher@example.com",
        "display_name": "E2E Dispatcher",
        "role": "dispatcher",
        "tenant_id": 1,
        "site_id": 1,
    },
]

# Shared E2E password for all test users
E2E_PASSWORD = "E2ETestPassword123!"


def seed_e2e_data():
    """Seed E2E test data (idempotent)."""
    # Support legacy single-user mode via env vars
    email = os.getenv("E2E_TEST_EMAIL", "e2e-test@example.com")
    password = os.getenv("E2E_TEST_PASSWORD", E2E_PASSWORD)

    print(f"[INFO] Seeding E2E test data...")
    print(f"  Email: {email}")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # =========================================================
            # 1. Create test tenant (idempotent)
            # =========================================================
            print("[INFO] Creating tenant...")
            # Generate a dummy api_key_hash for E2E testing
            import hashlib
            e2e_api_key_hash = hashlib.sha256(b"e2e-test-api-key-not-for-production").hexdigest()

            cur.execute("""
                INSERT INTO tenants (id, name, api_key_hash, is_active)
                VALUES (1, 'E2E Test Tenant', %s, true)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    api_key_hash = EXCLUDED.api_key_hash,
                    is_active = EXCLUDED.is_active
                RETURNING id
            """, (e2e_api_key_hash,))
            tenant_id = cur.fetchone()[0]
            print(f"  [OK] Tenant ID: {tenant_id}")

            # =========================================================
            # 2. Create test site (skip if sites table doesn't exist)
            # =========================================================
            print("[INFO] Creating site...")
            site_id = None

            # Check if sites table exists first to avoid transaction abort
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'sites'
                )
            """)
            sites_exists = cur.fetchone()[0]

            if sites_exists:
                cur.execute("""
                    INSERT INTO sites (id, tenant_id, code, name, is_active)
                    VALUES (1, 1, 'e2e-site', 'E2E Test Site', true)
                    ON CONFLICT (id) DO UPDATE SET
                        tenant_id = EXCLUDED.tenant_id,
                        code = EXCLUDED.code,
                        name = EXCLUDED.name,
                        is_active = EXCLUDED.is_active
                    RETURNING id
                """)
                site_id = cur.fetchone()[0]
                print(f"  [OK] Site ID: {site_id}")
            else:
                print("  [WARN] sites table not found - E2E bindings will have NULL site_id")

            # =========================================================
            # 3. Ensure auth schema exists
            # =========================================================
            print("[INFO] Checking auth schema...")
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'auth' AND table_name = 'users'
                )
            """)
            auth_exists = cur.fetchone()[0]

            if not auth_exists:
                print("  [WARN] auth.users table not found - migrations may be incomplete")
                print("  [INFO] Attempting to create minimal auth schema...")

                # Create minimal auth schema for E2E
                cur.execute("""
                    CREATE SCHEMA IF NOT EXISTS auth;

                    CREATE TABLE IF NOT EXISTS auth.roles (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(50) UNIQUE NOT NULL,
                        description TEXT
                    );

                    INSERT INTO auth.roles (name, description) VALUES
                        ('platform_admin', 'Full platform access'),
                        ('tenant_admin', 'Full tenant access'),
                        ('dispatcher', 'Day-to-day operations'),
                        ('ops_readonly', 'Read-only access')
                    ON CONFLICT (name) DO NOTHING;

                    CREATE TABLE IF NOT EXISTS auth.users (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        email VARCHAR(255) UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        display_name VARCHAR(255),
                        is_active BOOLEAN DEFAULT true,
                        is_locked BOOLEAN DEFAULT false,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS auth.user_bindings (
                        id SERIAL PRIMARY KEY,
                        user_id UUID REFERENCES auth.users(id),
                        tenant_id INTEGER REFERENCES tenants(id),
                        site_id INTEGER REFERENCES sites(id),
                        role_id INTEGER REFERENCES auth.roles(id),
                        is_active BOOLEAN DEFAULT true,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS auth.sessions (
                        id SERIAL PRIMARY KEY,
                        user_id UUID REFERENCES auth.users(id),
                        token_hash VARCHAR(64) NOT NULL,
                        is_platform_scope BOOLEAN DEFAULT false,
                        expires_at TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS auth.audit_log (
                        id SERIAL PRIMARY KEY,
                        event_type VARCHAR(100) NOT NULL,
                        user_id UUID,
                        tenant_id INTEGER,
                        target_tenant_id INTEGER,
                        details TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
                print("  [OK] Minimal auth schema created")

            # =========================================================
            # 4. Get platform_admin role (should exist from migrations)
            # =========================================================
            print("[INFO] Looking up platform_admin role...")

            # Get role ID
            cur.execute("SELECT id FROM auth.roles WHERE name = 'platform_admin'")
            role_row = cur.fetchone()
            if not role_row:
                print("  [ERROR] platform_admin role not found!")
                sys.exit(1)
            role_id = role_row[0]
            print(f"  [OK] Role ID: {role_id}")

            # =========================================================
            # 5. Create or update test user
            # =========================================================
            print("[INFO] Creating test user...")
            password_hash = hash_password(password)

            # Check if user exists
            cur.execute(
                "SELECT id FROM auth.users WHERE LOWER(email) = LOWER(%s)",
                (email,)
            )
            existing = cur.fetchone()

            if existing:
                # Update existing user
                user_id = existing[0]
                cur.execute("""
                    UPDATE auth.users
                    SET password_hash = %s, is_active = true, is_locked = false
                    WHERE id = %s
                """, (password_hash, user_id))
                print(f"  [OK] Updated existing user: {user_id}")
            else:
                # Create new user
                cur.execute("""
                    INSERT INTO auth.users (email, password_hash, display_name, is_active)
                    VALUES (%s, %s, %s, true)
                    RETURNING id
                """, (email.lower(), password_hash, "E2E Test User"))
                user_id = cur.fetchone()[0]
                print(f"  [OK] Created new user: {user_id}")

            # =========================================================
            # 6. Create user binding (platform_admin bound to E2E tenant)
            # =========================================================
            print("[INFO] Creating user binding...")

            # Remove existing bindings for this user
            cur.execute(
                "DELETE FROM auth.user_bindings WHERE user_id = %s",
                (str(user_id),)
            )

            # Create platform_admin binding (bound to E2E tenant for testing)
            # Note: Schema requires tenant_id NOT NULL, so we bind to test tenant
            cur.execute("""
                INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
                VALUES (%s, %s, %s, %s, true)
                RETURNING id
            """, (str(user_id), tenant_id, site_id, role_id))
            binding_id = cur.fetchone()[0]
            print(f"  [OK] Binding ID: {binding_id} (platform_admin, tenant={tenant_id})")

            # =========================================================
            # 7. Audit log for legacy user
            # =========================================================
            cur.execute("""
                INSERT INTO auth.audit_log (event_type, user_id, details)
                VALUES (%s, %s, %s)
            """, (
                "E2E_SEED_USER_CREATED",
                str(user_id),
                f'{{"email": "{email}", "role": "platform_admin", "seeded_by": "scripts/seed_e2e.py"}}'
            ))

            # =========================================================
            # 8. Create additional E2E users (deterministic)
            # =========================================================
            print("")
            print("[INFO] Creating additional E2E test users...")

            for e2e_user in E2E_TEST_USERS:
                e2e_id = e2e_user["id"]
                e2e_email = e2e_user["email"]
                e2e_display = e2e_user["display_name"]
                e2e_role = e2e_user["role"]
                e2e_tenant = e2e_user["tenant_id"]
                e2e_site = e2e_user["site_id"]

                # Get role ID
                cur.execute("SELECT id FROM auth.roles WHERE name = %s", (e2e_role,))
                role_row = cur.fetchone()
                if not role_row:
                    print(f"  [WARN] Role '{e2e_role}' not found, skipping user {e2e_email}")
                    continue
                e2e_role_id = role_row[0]

                # Create or update user with deterministic UUID
                # Use INSERT ... ON CONFLICT (id) - if email conflicts, the user already exists
                cur.execute("""
                    INSERT INTO auth.users (id, email, password_hash, display_name, is_active, is_locked)
                    VALUES (%s, %s, %s, %s, true, false)
                    ON CONFLICT (id) DO UPDATE SET
                        email = EXCLUDED.email,
                        password_hash = EXCLUDED.password_hash,
                        display_name = EXCLUDED.display_name,
                        is_active = true,
                        is_locked = false
                """, (e2e_id, e2e_email.lower(), password_hash, e2e_display))

                # Remove existing bindings
                cur.execute(
                    "DELETE FROM auth.user_bindings WHERE user_id = %s",
                    (e2e_id,)
                )

                # Create binding
                # For E2E purposes, all users are bound to the E2E test tenant
                # The platform_admin role determines access level, not tenant_id
                # Schema requires tenant_id NOT NULL, so we always bind to test tenant
                binding_tenant = e2e_tenant if e2e_tenant is not None else tenant_id
                binding_site = e2e_site if e2e_site is not None else site_id

                cur.execute("""
                    INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
                    VALUES (%s, %s, %s, %s, true)
                """, (e2e_id, binding_tenant, binding_site, e2e_role_id))

                print(f"  [OK] {e2e_role}: {e2e_email}")

            conn.commit()

            print("")
            print("=" * 60)
            print(" E2E SEED COMPLETE")
            print("=" * 60)
            print(f"  Tenant:  {tenant_id} (e2e-test)")
            print(f"  Site:    {site_id} (e2e-site)")
            print("")
            print("  Legacy User:")
            print(f"    Email:   {email}")
            print(f"    Role:    platform_admin")
            print("")
            print("  Additional E2E Users (all use same password):")
            for u in E2E_TEST_USERS:
                print(f"    {u['role']:15} -> {u['email']}")
            print("")
            print(f"  Password: {E2E_PASSWORD}")
            print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Seed failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    seed_e2e_data()
