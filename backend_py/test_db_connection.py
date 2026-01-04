#!/usr/bin/env python3
"""
Test Database Connection for SOLVEREIGN V3
==========================================

Purpose: Verify Postgres setup and schema initialization

Usage:
    python backend_py/test_db_connection.py

Prerequisites:
    1. docker-compose up -d postgres
    2. pip install psycopg[binary]
"""

import sys
from datetime import datetime

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("[ERROR] psycopg not installed")
    print("   Run: pip install 'psycopg[binary]'")
    sys.exit(1)


def test_connection():
    """Test basic database connection."""
    print("[TEST] Testing database connection...")

    try:
        conn = psycopg.connect(
            "host=localhost port=5432 dbname=solvereign user=solvereign password=dev_password_change_in_production",
            row_factory=dict_row
        )
        print("[OK] Connection successful!")
        return conn
    except psycopg.OperationalError as e:
        print(f"[ERROR] Connection failed: {e}")
        print("\n[HINT] Troubleshooting:")
        print("   1. Is Postgres running? → docker-compose up -d postgres")
        print("   2. Check docker logs → docker logs solvereign-db")
        print("   3. Verify port 5432 → docker ps | grep 5432")
        sys.exit(1)


def test_schema(conn):
    """Verify all tables exist."""
    print("\n[TEST] Testing database schema...")

    expected_tables = [
        'forecast_versions',
        'tours_raw',
        'tours_normalized',
        'plan_versions',
        'assignments',
        'audit_log',
        'freeze_windows',
        'diff_results'
    ]

    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        actual_tables = [row['tablename'] for row in cur.fetchall()]

    missing = set(expected_tables) - set(actual_tables)
    extra = set(actual_tables) - set(expected_tables)

    if missing:
        print(f"[FAIL] Missing tables: {', '.join(missing)}")
        return False

    if extra:
        print(f"[INFO] Extra tables: {', '.join(extra)}")

    print(f"[OK] All {len(expected_tables)} MVP tables found!")
    return True


def test_views(conn):
    """Verify utility views exist."""
    print("\n[TEST] Testing utility views...")

    expected_views = [
        'latest_locked_plans',
        'release_ready_plans'
    ]

    with conn.cursor() as cur:
        cur.execute("""
            SELECT viewname FROM pg_views
            WHERE schemaname = 'public'
            ORDER BY viewname
        """)
        actual_views = [row['viewname'] for row in cur.fetchall()]

    missing = set(expected_views) - set(actual_views)

    if missing:
        print(f"[FAIL] Missing views: {', '.join(missing)}")
        return False

    print(f"[OK] All {len(expected_views)} utility views found!")
    return True


def test_freeze_windows(conn):
    """Verify default freeze window rules."""
    print("\n[TEST] Testing freeze window configuration...")

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM freeze_windows ORDER BY rule_name")
        rules = cur.fetchall()

    if not rules:
        print("[FAIL] No freeze window rules found!")
        return False

    print(f"[OK] Found {len(rules)} freeze window rules:")
    for rule in rules:
        enabled_icon = "[ACTIVE]" if rule['enabled'] else "[PAUSED]"
        print(f"   {enabled_icon} {rule['rule_name']}: {rule['minutes_before_start']}min -> {rule['behavior']}")

    return True


def test_initial_data(conn):
    """Verify placeholder forecast version exists."""
    print("\n[TEST] Testing initial data...")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM forecast_versions")
        count = cur.fetchone()['count']

    if count == 0:
        print("[FAIL] No forecast versions found (expected placeholder)")
        return False

    print(f"[OK] Found {count} forecast version(s)")
    return True


def test_roundtrip(conn):
    """Test roundtrip: write → read → verify."""
    print("\n[TEST] Testing database roundtrip...")

    test_forecast = {
        'source': 'manual',
        'input_hash': f'test_hash_{datetime.now().timestamp()}',
        'parser_config_hash': 'v3.0.0-test',
        'status': 'PASS',
        'notes': 'Roundtrip test from test_db_connection.py'
    }

    try:
        with conn.cursor() as cur:
            # Insert
            cur.execute("""
                INSERT INTO forecast_versions (source, input_hash, parser_config_hash, status, notes)
                VALUES (%(source)s, %(input_hash)s, %(parser_config_hash)s, %(status)s, %(notes)s)
                RETURNING id
            """, test_forecast)
            forecast_id = cur.fetchone()['id']
            conn.commit()
            print(f"   [OK] Insert successful (id={forecast_id})")

            # Read
            cur.execute("SELECT * FROM forecast_versions WHERE id = %s", (forecast_id,))
            result = cur.fetchone()
            print(f"   [OK] Read successful (source={result['source']})")

            # Cleanup
            cur.execute("DELETE FROM forecast_versions WHERE id = %s", (forecast_id,))
            conn.commit()
            print(f"   [OK] Cleanup successful")

        return True

    except Exception as e:
        print(f"   [FAIL] Roundtrip failed: {e}")
        conn.rollback()
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("SOLVEREIGN V3 Database Test Suite")
    print("=" * 70)

    # Test 1: Connection
    conn = test_connection()

    # Test 2: Schema
    if not test_schema(conn):
        conn.close()
        sys.exit(1)

    # Test 3: Views
    if not test_views(conn):
        conn.close()
        sys.exit(1)

    # Test 4: Freeze Windows
    if not test_freeze_windows(conn):
        conn.close()
        sys.exit(1)

    # Test 5: Initial Data
    if not test_initial_data(conn):
        conn.close()
        sys.exit(1)

    # Test 6: Roundtrip
    if not test_roundtrip(conn):
        conn.close()
        sys.exit(1)

    # Success!
    conn.close()
    print("\n" + "=" * 70)
    print("[SUCCESS] ALL TESTS PASSED!")
    print("=" * 70)
    print("\n[INFO] Next Steps:")
    print("   1. Implement M1 (Parser): backend_py/v3/parser.py")
    print("   2. Implement M4 (Solver Wrapper): backend_py/v3/solver_wrapper.py")
    print("   3. Implement M3 (Diff Engine): backend_py/v3/diff_engine.py")
    print("   4. See: backend_py/V3_IMPLEMENTATION.md")
    print()


if __name__ == "__main__":
    main()
