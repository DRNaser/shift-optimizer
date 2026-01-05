"""
Setup Test Tenant
=================
Creates a test tenant with a known API key for Gate 3 testing.
"""

import hashlib
import psycopg
from psycopg.rows import dict_row
import os

DB_DSN = os.getenv("DATABASE_URL", "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign")

# Test API key (must be >= 32 characters)
TEST_API_KEY = "test-api-key-for-gate-3-validation-123456789"
TEST_API_KEY_B = "test-api-key-tenant-b-for-isolation-test"

def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()

def main():
    print("Setting up test tenants...")
    print(f"API Key A: {TEST_API_KEY} (hash: {sha256(TEST_API_KEY)[:16]}...)")
    print(f"API Key B: {TEST_API_KEY_B} (hash: {sha256(TEST_API_KEY_B)[:16]}...)")

    with psycopg.connect(DB_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Update default tenant with test API key hash
            cur.execute("""
                UPDATE tenants
                SET api_key_hash = %s,
                    name = 'test_tenant_a'
                WHERE id = 1
            """, (sha256(TEST_API_KEY),))

            # Create tenant B for isolation testing
            cur.execute("""
                INSERT INTO tenants (name, api_key_hash, is_active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (api_key_hash) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """, ('test_tenant_b', sha256(TEST_API_KEY_B)))

            tenant_b = cur.fetchone()
            print(f"Tenant B ID: {tenant_b['id'] if tenant_b else 'already exists'}")

            conn.commit()

            # Verify
            cur.execute("SELECT id, name, api_key_hash, is_active FROM tenants")
            tenants = cur.fetchall()
            print("\nTenants in database:")
            for t in tenants:
                print(f"  ID {t['id']}: {t['name']} (hash: {t['api_key_hash'][:16]}..., active: {t['is_active']})")

    print("\nTest tenants setup complete!")
    print(f"\nUse these headers for testing:")
    print(f'  Tenant A: -H "X-API-Key: {TEST_API_KEY}"')
    print(f'  Tenant B: -H "X-API-Key: {TEST_API_KEY_B}"')

if __name__ == "__main__":
    main()
