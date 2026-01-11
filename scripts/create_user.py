#!/usr/bin/env python3
"""
SOLVEREIGN V4.5 - User Management CLI
======================================

Create and manage internal RBAC users.

SECURITY: Never pass passwords on command line! Use one of:
  1. Interactive prompt (recommended): Omit --password, script will prompt securely
  2. Environment variable: export USER_PASSWORD=... (cleared after use)

Usage:
    # Bootstrap first platform admin (one-time setup)
    python scripts/create_user.py bootstrap-platform-admin
    # → Password will be prompted securely (no echo)

    # Create a new user (password prompt)
    python scripts/create_user.py create \\
        --email <user-email> \\
        --name "<Display Name>" \\
        --tenant <tenant-id> \\
        --site <site-id> \\
        --role <role>
    # → Password will be prompted securely (no echo)

    # List users
    python scripts/create_user.py list

    # Hash a password (interactive prompt)
    python scripts/create_user.py hash-password

    # Verify RBAC integrity
    python scripts/create_user.py verify

Environment:
    DATABASE_URL: PostgreSQL connection string
    USER_PASSWORD: (optional) Password for non-interactive mode (CI only)
"""

import argparse
import os
import sys
import getpass
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


def hash_password_cmd(args):
    """Hash a password using Argon2id."""
    from backend_py.api.security.internal_rbac import hash_password

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")

    hashed = hash_password(password)
    print(f"\nArgon2id hash:\n{hashed}\n")
    print("Use this in SQL:")
    print(f"  password_hash = '{hashed}'")


def create_user_cmd(args):
    """Create a new user with binding."""
    from backend_py.api.security.internal_rbac import hash_password
    import uuid

    # Validate required args
    if not args.email:
        print("ERROR: --email is required")
        sys.exit(1)

    # Password priority: 1) CLI arg, 2) USER_PASSWORD env, 3) interactive prompt
    password = args.password
    if not password:
        password = os.getenv("USER_PASSWORD")
        if password:
            print("Using password from USER_PASSWORD environment variable")
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

    tenant_id = args.tenant
    if not tenant_id:
        print("ERROR: --tenant is required")
        sys.exit(1)

    role = args.role or "dispatcher"

    # Hash password
    password_hash = hash_password(password)

    # Generate user ID
    user_id = str(uuid.uuid4())

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Check if user exists
            cur.execute(
                "SELECT id FROM auth.users WHERE LOWER(email) = LOWER(%s)",
                (args.email,)
            )
            existing = cur.fetchone()
            if existing:
                print(f"ERROR: User with email {args.email} already exists")
                sys.exit(1)

            # Get role ID
            cur.execute(
                "SELECT id FROM auth.roles WHERE name = %s",
                (role,)
            )
            role_row = cur.fetchone()
            if not role_row:
                print(f"ERROR: Role '{role}' not found")
                print("Available roles: platform_admin, operator_admin, dispatcher, ops_readonly")
                sys.exit(1)
            role_id = role_row[0]

            # Check tenant exists
            cur.execute(
                "SELECT id FROM tenants WHERE id = %s",
                (tenant_id,)
            )
            if not cur.fetchone():
                print(f"ERROR: Tenant {tenant_id} not found")
                sys.exit(1)

            # Check site exists (if provided)
            if args.site:
                cur.execute(
                    "SELECT id FROM sites WHERE id = %s AND tenant_id = %s",
                    (args.site, tenant_id)
                )
                if not cur.fetchone():
                    print(f"ERROR: Site {args.site} not found in tenant {tenant_id}")
                    sys.exit(1)

            # Create user
            cur.execute(
                """
                INSERT INTO auth.users (id, email, password_hash, display_name, is_active)
                VALUES (%s, %s, %s, %s, true)
                RETURNING id
                """,
                (user_id, args.email.lower(), password_hash, args.name)
            )
            created_user_id = str(cur.fetchone()[0])

            # Create binding
            cur.execute(
                """
                INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
                VALUES (%s, %s, %s, %s, true)
                RETURNING id
                """,
                (created_user_id, tenant_id, args.site, role_id)
            )
            binding_id = cur.fetchone()[0]

            # Audit log: user creation
            cur.execute(
                """
                INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    "USER_CREATED_VIA_CLI",
                    created_user_id,
                    tenant_id,
                    f'{{"email": "{args.email.lower()}", "role": "{role}", "site_id": {args.site or "null"}, "created_by": "scripts/create_user.py"}}'
                )
            )

            conn.commit()

            print(f"\n✅ User created successfully!")
            print(f"   User ID:    {created_user_id}")
            print(f"   Email:      {args.email}")
            print(f"   Name:       {args.name or '(not set)'}")
            print(f"   Tenant ID:  {tenant_id}")
            print(f"   Site ID:    {args.site or '(all sites)'}")
            print(f"   Role:       {role}")
            print(f"   Binding ID: {binding_id}")
            print(f"   Audit:      USER_CREATED_VIA_CLI event logged")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


def list_users_cmd(args):
    """List all users with their bindings."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.id,
                    u.email,
                    u.display_name,
                    u.is_active,
                    u.is_locked,
                    b.tenant_id,
                    b.site_id,
                    r.name as role_name
                FROM auth.users u
                LEFT JOIN auth.user_bindings b ON u.id = b.user_id AND b.is_active = true
                LEFT JOIN auth.roles r ON b.role_id = r.id
                ORDER BY u.email, b.tenant_id
                """
            )
            rows = cur.fetchall()

            if not rows:
                print("No users found.")
                return

            print(f"\n{'Email':<30} {'Name':<20} {'Active':<8} {'Tenant':<8} {'Site':<8} {'Role':<15}")
            print("-" * 100)

            for row in rows:
                user_id, email, name, is_active, is_locked, tenant_id, site_id, role_name = row
                status = "Locked" if is_locked else ("Yes" if is_active else "No")
                print(f"{email:<30} {(name or '-'):<20} {status:<8} {str(tenant_id or '-'):<8} {str(site_id or '-'):<8} {(role_name or '-'):<15}")

            print(f"\nTotal: {len(rows)} binding(s)")

    finally:
        conn.close()


def verify_cmd(args):
    """Run RBAC integrity verification."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM auth.verify_rbac_integrity()")
            rows = cur.fetchall()

            print("\n" + "=" * 60)
            print("RBAC Integrity Check")
            print("=" * 60 + "\n")

            all_pass = True
            for row in rows:
                check_name, status, details = row[0], row[1], row[2] if len(row) > 2 else None
                icon = "✅" if status == "PASS" else "❌"
                print(f"{icon} {check_name}: {status}")
                if details:
                    print(f"   {details}")
                if status != "PASS":
                    all_pass = False

            print("\n" + "=" * 60)
            if all_pass:
                print("✅ All checks passed!")
            else:
                print("❌ Some checks failed!")
            print("=" * 60 + "\n")

    finally:
        conn.close()


def cleanup_sessions_cmd(args):
    """Clean up expired sessions."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Count expired sessions
            cur.execute(
                """
                SELECT COUNT(*) FROM auth.sessions
                WHERE expires_at < NOW() OR revoked_at IS NOT NULL
                """
            )
            count = cur.fetchone()[0]

            if count == 0:
                print("No expired sessions to clean up.")
                return

            if not args.force:
                confirm = input(f"Delete {count} expired/revoked sessions? [y/N] ")
                if confirm.lower() != 'y':
                    print("Cancelled.")
                    return

            # Delete expired sessions
            cur.execute(
                """
                DELETE FROM auth.sessions
                WHERE expires_at < NOW() OR revoked_at IS NOT NULL
                """
            )
            conn.commit()

            print(f"✅ Deleted {count} expired/revoked sessions.")

    finally:
        conn.close()


def bootstrap_platform_admin_cmd(args):
    """
    Bootstrap the first platform admin.

    This command creates the first platform_admin user only if no platform_admin exists.
    Use this for initial system setup.

    SECURITY: Password is prompted interactively (never on command line).
    """
    from backend_py.api.security.internal_rbac import hash_password
    import uuid
    import json

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Check if any platform_admin exists
            cur.execute(
                """
                SELECT COUNT(*) FROM auth.user_bindings ub
                JOIN auth.roles r ON r.id = ub.role_id
                WHERE r.name = 'platform_admin' AND ub.is_active = TRUE
                """
            )
            existing_count = cur.fetchone()[0]

            if existing_count > 0:
                print("ERROR: Platform admin already exists. Bootstrap is only for initial setup.")
                print("Use 'create' command to add additional users.")
                sys.exit(1)

            print("\n" + "=" * 60)
            print("SOLVEREIGN Platform Admin Bootstrap")
            print("=" * 60)
            print("\nThis will create the first platform administrator.")
            print("Platform admins have full access to all tenants and features.\n")

            # Get email
            email = args.email
            if not email:
                email = input("Email: ").strip()
            if not email or '@' not in email:
                print("ERROR: Valid email is required")
                sys.exit(1)

            # Get display name
            name = args.name
            if not name:
                name = input("Display name: ").strip()

            # Get password
            password = os.getenv("USER_PASSWORD")
            if password:
                print("Using password from USER_PASSWORD environment variable")
                os.environ.pop("USER_PASSWORD", None)
            else:
                password = getpass.getpass("Password: ")
                confirm = getpass.getpass("Confirm password: ")
                if password != confirm:
                    print("ERROR: Passwords do not match")
                    sys.exit(1)

            if len(password) < 12:
                print("ERROR: Platform admin password must be at least 12 characters")
                sys.exit(1)

            # Check email uniqueness
            cur.execute(
                "SELECT id FROM auth.users WHERE LOWER(email) = LOWER(%s)",
                (email,)
            )
            if cur.fetchone():
                print(f"ERROR: User with email {email} already exists")
                sys.exit(1)

            # Get platform_admin role ID
            cur.execute(
                "SELECT id FROM auth.roles WHERE name = 'platform_admin'"
            )
            role_row = cur.fetchone()
            if not role_row:
                print("ERROR: platform_admin role not found. Run migration 039_internal_rbac.sql first.")
                sys.exit(1)
            role_id = role_row[0]

            # Hash password
            password_hash = hash_password(password)

            # Generate user ID
            user_id = str(uuid.uuid4())

            # Create user
            cur.execute(
                """
                INSERT INTO auth.users (id, email, password_hash, display_name, is_active)
                VALUES (%s, %s, %s, %s, true)
                RETURNING id
                """,
                (user_id, email.lower(), password_hash, name)
            )
            created_user_id = str(cur.fetchone()[0])

            # Create platform_admin binding (no tenant/site - platform-wide access)
            # For Model 1: platform_admin has tenant_id=0 (platform scope)
            # We'll use a special "platform" tenant (id=0) for platform admins
            cur.execute(
                """
                INSERT INTO auth.user_bindings (user_id, tenant_id, site_id, role_id, is_active)
                VALUES (%s, 0, NULL, %s, true)
                RETURNING id
                """,
                (created_user_id, role_id)
            )
            binding_id = cur.fetchone()[0]

            # Audit log: platform admin bootstrap
            cur.execute(
                """
                INSERT INTO auth.audit_log (event_type, user_id, tenant_id, details)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    "PLATFORM_ADMIN_BOOTSTRAPPED",
                    created_user_id,
                    None,
                    json.dumps({
                        "email": email.lower(),
                        "created_by": "scripts/create_user.py bootstrap-platform-admin",
                        "is_first_admin": True
                    })
                )
            )

            conn.commit()

            print(f"\n✅ Platform admin created successfully!")
            print(f"   User ID:    {created_user_id}")
            print(f"   Email:      {email}")
            print(f"   Name:       {name or '(not set)'}")
            print(f"   Role:       platform_admin")
            print(f"   Scope:      Platform-wide (all tenants)")
            print(f"   Binding ID: {binding_id}")
            print(f"   Audit:      PLATFORM_ADMIN_BOOTSTRAPPED event logged")
            print(f"\nYou can now login at /platform/login")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN V4.5 - User Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Bootstrap first platform admin (one-time setup)
  python scripts/create_user.py bootstrap-platform-admin

  # Create user (password prompted securely)
  python scripts/create_user.py create --email <email> --tenant <id> --site <id> --role <role>

  # List all users
  python scripts/create_user.py list

  # Hash password (interactive prompt, no echo)
  python scripts/create_user.py hash-password

  # Verify RBAC integrity
  python scripts/create_user.py verify

  # Clean up expired sessions
  python scripts/create_user.py cleanup-sessions --force

Security: NEVER pass passwords on command line - use interactive prompt!
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a new user")
    create_parser.add_argument("--email", "-e", required=True, help="User email")
    create_parser.add_argument("--password", "-p", help="Password (will prompt if not provided)")
    create_parser.add_argument("--name", "-n", help="Display name")
    create_parser.add_argument("--tenant", "-t", type=int, required=True, help="Tenant ID")
    create_parser.add_argument("--site", "-s", type=int, help="Site ID (optional)")
    create_parser.add_argument(
        "--role", "-r",
        choices=["platform_admin", "operator_admin", "dispatcher", "ops_readonly"],
        default="dispatcher",
        help="Role (default: dispatcher)"
    )

    # list command
    list_parser = subparsers.add_parser("list", help="List all users")

    # hash-password command
    hash_parser = subparsers.add_parser("hash-password", help="Hash a password")
    hash_parser.add_argument("password", nargs="?", help="Password to hash (will prompt if not provided)")

    # verify command
    verify_parser = subparsers.add_parser("verify", help="Verify RBAC integrity")

    # cleanup-sessions command
    cleanup_parser = subparsers.add_parser("cleanup-sessions", help="Clean up expired sessions")
    cleanup_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

    # bootstrap-platform-admin command
    bootstrap_parser = subparsers.add_parser(
        "bootstrap-platform-admin",
        help="Bootstrap first platform admin (one-time setup)"
    )
    bootstrap_parser.add_argument("--email", "-e", help="Admin email (will prompt if not provided)")
    bootstrap_parser.add_argument("--name", "-n", help="Display name (will prompt if not provided)")

    args = parser.parse_args()

    if args.command == "create":
        create_user_cmd(args)
    elif args.command == "list":
        list_users_cmd(args)
    elif args.command == "hash-password":
        hash_password_cmd(args)
    elif args.command == "verify":
        verify_cmd(args)
    elif args.command == "cleanup-sessions":
        cleanup_sessions_cmd(args)
    elif args.command == "bootstrap-platform-admin":
        bootstrap_platform_admin_cmd(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
