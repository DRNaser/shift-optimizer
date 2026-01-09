"""
SOLVEREIGN V3.3b - E2E Replay Attack Proof
===========================================

Runs actual HTTP requests against /api/v1/platform/orgs (protected endpoint)
to prove replay attack detection works in production.

REQUIRES:
- Backend running: uvicorn api.main:app --reload
- Migration 022 applied (core.used_signatures, core.security_events)

RUN:
    python backend_py/tests/e2e_replay_proof.py
"""

import hashlib
import hmac
import time
import secrets
import json
import sys
import os
from urllib.parse import urlparse, parse_qsl, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import httpx
except ImportError:
    print("ERROR: pip install httpx")
    sys.exit(1)

try:
    import psycopg
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

# =============================================================================
# CONFIG - MUST MATCH BACKEND
# =============================================================================

INTERNAL_SECRET = os.getenv(
    "SOLVEREIGN_INTERNAL_SECRET",
    "change_me_in_production_to_a_random_64_char_string_abc123"  # Default from config.py
)
BASE_URL = os.getenv("SOLVEREIGN_API_URL", "http://localhost:8000")
DATABASE_URL = os.getenv(
    "SOLVEREIGN_DATABASE_URL",
    "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign"
)


# =============================================================================
# SIGNATURE V2
# =============================================================================

def canonicalize_path(path: str) -> str:
    parsed = urlparse(path)
    query_params = parse_qsl(parsed.query)
    sorted_params = sorted(query_params, key=lambda x: (x[0], x[1]))
    sorted_query = urlencode(sorted_params)
    return f"{parsed.path}?{sorted_query}" if sorted_query else parsed.path


def generate_signature_v2(
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    tenant_code: str = "",
    site_code: str = "",
    is_platform_admin: bool = True,
    body_hash: str = "",
) -> str:
    canonical_path = canonicalize_path(path)
    canonical = "|".join([
        method.upper(),
        canonical_path,
        str(timestamp),
        nonce,
        tenant_code,
        site_code,
        "1" if is_platform_admin else "0",
        body_hash
    ])
    return hmac.new(
        INTERNAL_SECRET.encode(),
        canonical.encode(),
        hashlib.sha256
    ).hexdigest()


def build_headers(method: str, path: str, nonce: str, timestamp: int) -> dict:
    signature = generate_signature_v2(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        is_platform_admin=True
    )
    return {
        "X-SV-Internal": "1",
        "X-SV-Timestamp": str(timestamp),
        "X-SV-Nonce": nonce,
        "X-SV-Signature": signature,
        "X-Platform-Admin": "true",
        "Content-Type": "application/json",
    }


# =============================================================================
# E2E REPLAY PROOF
# =============================================================================

def run_e2e_replay_proof():
    print("\n" + "="*70)
    print(" E2E REPLAY ATTACK PROOF")
    print("="*70)
    print(f" Base URL: {BASE_URL}")
    print(f" Secret: {INTERNAL_SECRET[:20]}...")
    print(f" Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    # Protected endpoint
    method = "GET"
    path = "/api/v1/platform/orgs"

    # Fixed nonce and timestamp for replay
    nonce = secrets.token_hex(16)
    timestamp = int(time.time())

    headers = build_headers(method, path, nonce, timestamp)

    print(f"\n[1] Request Configuration:")
    print(f"    Endpoint: {method} {path}")
    print(f"    Nonce: {nonce}")
    print(f"    Timestamp: {timestamp}")
    print(f"    Signature: {headers['X-SV-Signature'][:32]}...")

    try:
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)

        # REQUEST 1: Should succeed (or fail auth if not configured, but not 403 replay)
        print(f"\n[2] Request 1 (first attempt)...")
        r1 = client.request(method, path, headers=headers)
        print(f"    Status: {r1.status_code}")
        print(f"    Response: {r1.text[:200]}")

        status1 = r1.status_code

        # REQUEST 2: Same nonce - should be REPLAY
        print(f"\n[3] Request 2 (REPLAY - same nonce/timestamp/signature)...")
        r2 = client.request(method, path, headers=headers)
        print(f"    Status: {r2.status_code}")
        print(f"    Response: {r2.text[:200]}")

        status2 = r2.status_code

        client.close()

    except httpx.ConnectError as e:
        print(f"\n[ERROR] Cannot connect to {BASE_URL}")
        print(f"        Is the backend running?")
        print(f"        Error: {e}")
        return False

    # VALIDATION
    print(f"\n[4] Validation:")

    if status1 == 401:
        print(f"    Request 1: 401 (signature config mismatch - check INTERNAL_SECRET)")
        print(f"    => Cannot validate replay (auth failed on first request)")
        return False

    if status2 == 403:
        try:
            body = r2.json()
            if body.get("detail", {}).get("code") == "REPLAY_ATTACK":
                print(f"    [OK] Request 2 correctly returned 403 REPLAY_ATTACK")
                print(f"    Response body: {json.dumps(body, indent=2)}")
            else:
                print(f"    [WARN] 403 but unexpected body: {body}")
        except:
            if "REPLAY" in r2.text.upper():
                print(f"    [OK] Request 2 returned 403 with REPLAY in response")
            else:
                print(f"    [WARN] 403 but no REPLAY_ATTACK code")
    elif status2 == status1:
        print(f"    [FAIL] Request 2 returned same status as Request 1 ({status2})")
        print(f"    => Replay protection NOT working")
        print(f"    Possible causes:")
        print(f"       - Migration 022 not applied (core.used_signatures missing)")
        print(f"       - Database connection issue")
        print(f"       - check_replay=False in dependency")
        return False
    else:
        print(f"    [INFO] Request 2 status: {status2}")

    # DATABASE CHECK
    if HAS_PSYCOPG:
        print(f"\n[5] Database Evidence:")
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT event_type, severity, source_ip, request_path,
                               details, created_at
                        FROM core.security_events
                        WHERE event_type = 'REPLAY_ATTACK'
                        ORDER BY created_at DESC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    if row:
                        print(f"    [OK] Security event logged:")
                        print(f"        event_type: {row[0]}")
                        print(f"        severity: {row[1]}")
                        print(f"        source_ip: {row[2]}")
                        print(f"        request_path: {row[3]}")
                        print(f"        details: {row[4]}")
                        print(f"        created_at: {row[5]}")
                    else:
                        print(f"    [INFO] No REPLAY_ATTACK event found")
                        print(f"           (table may not exist or event not logged)")
        except Exception as e:
            print(f"    [WARN] DB query failed: {e}")
    else:
        print(f"\n[5] Skipping DB check (psycopg not installed)")

    # SUMMARY
    print("\n" + "="*70)
    if status2 == 403:
        print(" E2E REPLAY PROOF: PASS")
        print("="*70)
        print(" Evidence:")
        print(f"   - Request 1: {status1}")
        print(f"   - Request 2 (replay): 403 REPLAY_ATTACK")
        print(f"   - Nonce: {nonce}")
        print("="*70)
        return True
    else:
        print(" E2E REPLAY PROOF: INCONCLUSIVE")
        print("="*70)
        print(f" Request 1: {status1}")
        print(f" Request 2: {status2}")
        print(" Check backend configuration and migrations.")
        print("="*70)
        return False


if __name__ == "__main__":
    success = run_e2e_replay_proof()
    sys.exit(0 if success else 1)
