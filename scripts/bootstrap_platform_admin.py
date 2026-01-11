#!/usr/bin/env python3
"""
SOLVEREIGN - Bootstrap Platform Admin (Idempotent)
===================================================

Creates or updates a platform admin user. Idempotent: safe to run multiple times.

SECURITY:
- Never logs passwords or secrets
- Uses same Argon2id hashing as /api/auth/login
- Output only: CREATED / UPDATED / NOOP

Usage:
    python scripts/bootstrap_platform_admin.py \\
        --email "user@example.com" \\
        --password "SecurePassword123!" \\
        --display-name "Display Name" \\
        --verify-email \\
        --role platform_admin

    # Disable mock admin (optional)
    python scripts/bootstrap_platform_admin.py \\
        --email "user@example.com" \\
        --password "SecurePassword123!" \\
        --disable-mock-admin

Environment:
    DATABASE_URL: PostgreSQL connection string (required)
"""

import argparse
import os
import sys
import json
import getpass
import secrets
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows console fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def get_connection():
    """Get database connection."""
    import psycopg

    # Support both env var names (container uses SOLVEREIGN_DATABASE_URL)
    database_url = os.getenv("DATABASE_URL") or os.getenv("SOLVEREIGN_DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL or SOLVEREIGN_DATABASE_URL environment variable not set")
        sys.exit(1)

    return psycopg.connect(database_url)


def hash_password_internal(password: str) -> str:
    """
    Hash password using same Argon2id config as /api/auth/login.
    Imports from internal_rbac to ensure consistency.
    """
    try:
        # Docker container path (api is at /app/api)
        from api.security.internal_rbac import hash_password
    except ImportError:
        # Local development path (backend_py/api)
        from backend_py.api.security.internal_rbac import hash_password
    return hash_password(password)


def ensure_email_verified_column(cur) -> bool:
    """
    Ensure email_verified_at column exists. Returns True if it exists.
    """
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'auth'
            AND table_name = 'users'
            AND column_name = 'email_verified_at'
        )
    """)
    exists = cur.fetchone()[0]

    if not exists:
        # Add the column if it doesn't exist
        cur.execute("""
            ALTER TABLE auth.users
            ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ NULL
        """)
        return True
    return exists


def bootstrap_platform_admin(
    email: str,
    password: str,
    display_name: str | None = None,
    verify_email: bool = True,
    role_name: str = "platform_admin",
    disable_mock_admin: bool = False,
) -> dict:
    """
    Create or update platform admin user (idempotent).

    Returns:
        dict with keys: status (CREATED/UPDATED/NOOP), user_id, email, role, verified
    """
    result = {
        "status": "NOOP",
        "user_id": None,
        "email": email.lower(),
        "role": role_name,
        "verified": False,
        "mock_admin_disabled": False,
    }

    # Hash password using same algorithm as login
    password_hash = hash_password_internal(password)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Ensure email_verified_at column exists
            ensure_email_verified_column(cur)

            # Get role ID
            cur.execute(
                "SELECT id FROM auth.roles WHERE name = %s",
                (role_name,)
            )
            role_row = cur.fetchone()
            if not role_row:
                print(f"ERROR: Role '{role_name}' not found")
                print("Available roles: platform_admin, tenant_admin, operator_admin, dispatcher, ops_readonly")
                sys.exit(1)
            role_id = role_row[0]

            # Check if user exists
            cur.execute(
                "SELECT id, display_name, email_verified_at FROM auth.users WHERE LOWER(email) = LOWER(%s)",
                (email,)
            )
            existing_user = cur.fetchone()

            now = datetime.now(timezone.utc)

            if existing_user:
                # UPDATE existing user
                user_id = str(existing_user[0])
                current_name = existing_user[1]
                current_verified = existing_user[2]

                # Build update query
                update_parts = ["password_hash = %s", "updated_at = %s"]
                update_values = [password_hash, now]

                if display_name and display_name != current_name:
                    update_parts.append("display_name = %s")
                    update_values.append(display_name)

                if verify_email and current_verified is None:
                    update_parts.append("email_verified_at = %s")
                    update_values.append(now)
                    result["verified"] = True
                elif current_verified is not None:
                    result["verified"] = True

                # Ensure user is active
                update_parts.append("is_active = TRUE")
                update_parts.append("is_locked = FALSE")
                update_parts.append("failed_login_count = 0")

                update_values.append(user_id)

                cur.execute(
                    f"UPDATE auth.users SET {', '.join(update_parts)} WHERE id = %s",
                    tuple(update_values)
                )

                result["status"] = "UPDATED"
                result["user_id"] = user_id

            else:
                # CREATE new user
                import uuid
                user_id = str(uuid.uuid4())

                verified_at = now if verify_email else None
                result["verified"] = verify_email

                cur.execute(
                    """
                    INSERT INTO auth.users (id, email, password_hash, display_name, is_active, is_locked, email_verified_at)
                    VALUES (%s, %s, %s, %s, TRUE, FALSE, %s)
                    RETURNING id
                    """,
                    (user_id, email.lower(), password_hash, display_name, verified_at)
                )
                user_id = str(cur.fetchone()[0])

                result["status"] = "CREATED"
                result["user_id"] = user_id

            # Ensure platform_admin binding exists
            # Platform admin uses tenant_id=1 (matches existing admin@solvereign.com pattern)
            # Platform-wide access is granted via role, not tenant_id
            PLATFORM_ADMIN_TENANT_ID = 1

            cur.execute(
                """
                SELECT id FROM auth.user_bindings
                WHERE user_id = %s AND role_id = %s AND tenant_id = %s
                """,
                (user_id, role_id, PLATFORM_ADMIN_TENANT_ID)
            )
            existing_binding = cur.fetchone()

            if not existing_binding:
                cur.execute(
                    """
                    INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
                    VALUES (%s, %s, NULL, %s, TRUE)
                    """,
                    (user_id, PLATFORM_ADMIN_TENANT_ID, role_id)
                )
                if result["status"] == "NOOP":
                    result["status"] = "UPDATED"  # Binding was added
            else:
                # Ensure binding is active
                cur.execute(
                    "UPDATE auth.user_bindings SET is_active = TRUE WHERE id = %s",
                    (existing_binding[0],)
                )

            # Optional: Disable mock admin
            if disable_mock_admin:
                mock_email = "admin@solvereign.com"
                if email.lower() != mock_email.lower():
                    # Randomize password to disable access
                    random_pw = secrets.token_urlsafe(32)
                    random_hash = hash_password_internal(random_pw)

                    cur.execute(
                        """
                        UPDATE auth.users
                        SET password_hash = %s, is_active = FALSE, updated_at = %s
                        WHERE LOWER(email) = LOWER(%s)
                        """,
                        (random_hash, now, mock_email)
                    )
                    if cur.rowcount > 0:
                        result["mock_admin_disabled"] = True

            # Audit log
            cur.execute(
                """
                INSERT INTO auth.audit_log (event_type, user_id, details)
                VALUES (%s, %s, %s)
                """,
                (
                    f"PLATFORM_ADMIN_{result['status']}",
                    user_id,
                    json.dumps({
                        "email": email.lower(),
                        "role": role_name,
                        "verified": result["verified"],
                        "mock_admin_disabled": result["mock_admin_disabled"],
                        "created_by": "scripts/bootstrap_platform_admin.py",
                    })
                )
            )

            conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN - Bootstrap Platform Admin (Idempotent)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create/update platform admin with verified email
  python scripts/bootstrap_platform_admin.py \\
      --email "admin@example.com" \\
      --password "SecurePassword123!" \\
      --display-name "Admin User" \\
      --verify-email

  # Also disable mock admin
  python scripts/bootstrap_platform_admin.py \\
      --email "admin@example.com" \\
      --password "SecurePassword123!" \\
      --disable-mock-admin

SECURITY: Never pass passwords on command line in production!
          Use environment variable USER_PASSWORD instead.
        """
    )

    parser.add_argument(
        "--email", "-e",
        required=True,
        help="User email address"
    )
    parser.add_argument(
        "--password", "-p",
        help="User password (will use USER_PASSWORD env or prompt if not provided)"
    )
    parser.add_argument(
        "--display-name", "-n",
        help="Display name (optional)"
    )
    parser.add_argument(
        "--verify-email",
        action="store_true",
        default=True,
        help="Mark email as verified without email flow (default: True)"
    )
    parser.add_argument(
        "--no-verify-email",
        action="store_true",
        help="Do NOT mark email as verified"
    )
    parser.add_argument(
        "--role", "-r",
        default="platform_admin",
        choices=["platform_admin", "tenant_admin", "operator_admin", "dispatcher", "ops_readonly"],
        help="Role to assign (default: platform_admin)"
    )
    parser.add_argument(
        "--disable-mock-admin",
        action="store_true",
        default=False,
        help="Disable admin@solvereign.com mock account (optional, default: False)"
    )

    args = parser.parse_args()

    # Handle password: CLI arg > env var > prompt
    password = args.password
    if not password:
        password = os.getenv("USER_PASSWORD")
        if password:
            # Clear env var after reading (security)
            os.environ.pop("USER_PASSWORD", None)
        else:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("ERROR: Passwords do not match")
                sys.exit(1)

    if len(password) < 8:
        print("ERROR: Password must be at least 8 characters")
        sys.exit(1)

    # Handle verify-email flag
    verify_email = True
    if args.no_verify_email:
        verify_email = False

    # Run bootstrap
    result = bootstrap_platform_admin(
        email=args.email,
        password=password,
        display_name=args.display_name,
        verify_email=verify_email,
        role_name=args.role,
        disable_mock_admin=args.disable_mock_admin,
    )

    # Output result (never output password!)
    print(result["status"])

    # Verbose output for debugging (without secrets)
    if os.getenv("VERBOSE", "").lower() in ("1", "true", "yes"):
        print(f"  user_id:  {result['user_id']}")
        print(f"  email:    {result['email']}")
        print(f"  role:     {result['role']}")
        print(f"  verified: {result['verified']}")
        if result["mock_admin_disabled"]:
            print(f"  mock_admin_disabled: True")


if __name__ == "__main__":
    main()
