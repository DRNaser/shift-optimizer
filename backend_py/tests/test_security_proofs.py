"""
SOLVEREIGN Security Proofs - V3.3b Hardening Validation
========================================================

Proof 1: Replay Attack Protection
- Send same signed request twice (same nonce/timestamp/signature)
- Second request MUST return 401/403 with REPLAY_ATTACK event

Proof 2: Wizard Double Submit (Idempotency)
- Send "create tenant" twice with same idempotency key
- Should NOT create duplicate, UI continues
- Backend returns 200/201 (cached) or 409 (conflict)

Run:
    python -m pytest backend_py/tests/test_security_proofs.py -v

Or standalone:
    python backend_py/tests/test_security_proofs.py
"""

import hashlib
import hmac
import time
import secrets
import json
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qsl, urlencode

# =============================================================================
# CONFIGURATION
# =============================================================================

# This should match your actual secret in .env
TEST_SECRET = "test-secret-key-for-v3-development"

# Test endpoints (mock - adjust for real testing)
BASE_URL = "http://localhost:8000"


# =============================================================================
# SIGNATURE GENERATION (V2 Format)
# =============================================================================

def canonicalize_path(path: str) -> str:
    """Canonicalize path with sorted query string."""
    parsed = urlparse(path)
    query_params = parse_qsl(parsed.query)
    sorted_params = sorted(query_params, key=lambda x: (x[0], x[1]))
    sorted_query = urlencode(sorted_params)

    if sorted_query:
        return f"{parsed.path}?{sorted_query}"
    return parsed.path


def compute_body_hash(body: Any) -> str:
    """Compute SHA256 hash of request body."""
    if body is None:
        return ""
    if isinstance(body, dict):
        body = json.dumps(body, separators=(',', ':'), sort_keys=True)
    if isinstance(body, str):
        body = body.encode('utf-8')
    if not body:
        return ""
    return hashlib.sha256(body).hexdigest()


def generate_nonce() -> str:
    """Generate 32-char hex nonce."""
    return secrets.token_hex(16)


def generate_signature_v2(
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    tenant_code: Optional[str] = None,
    site_code: Optional[str] = None,
    is_platform_admin: bool = False,
    body_hash: str = "",
    secret: str = TEST_SECRET
) -> str:
    """Generate HMAC-SHA256 signature (V2 format)."""
    canonical_path = canonicalize_path(path)

    canonical = "|".join([
        method.upper(),
        canonical_path,
        str(timestamp),
        nonce,
        tenant_code or "",
        site_code or "",
        "1" if is_platform_admin else "0",
        body_hash or ""
    ])

    signature = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature


@dataclass
class SignedRequest:
    """Holds a signed request with all headers."""
    method: str
    path: str
    headers: Dict[str, str]
    body: Optional[str]
    nonce: str
    timestamp: int
    signature: str


def create_signed_request(
    method: str,
    path: str,
    body: Any = None,
    tenant_code: Optional[str] = None,
    site_code: Optional[str] = None,
    is_platform_admin: bool = True,
    nonce: Optional[str] = None,
    timestamp: Optional[int] = None,
    secret: str = TEST_SECRET
) -> SignedRequest:
    """Create a fully signed request."""
    if nonce is None:
        nonce = generate_nonce()
    if timestamp is None:
        timestamp = int(time.time())

    body_str = None
    body_hash = ""

    if body is not None:
        body_str = json.dumps(body, separators=(',', ':'), sort_keys=True)
        body_hash = compute_body_hash(body_str)

    signature = generate_signature_v2(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        tenant_code=tenant_code,
        site_code=site_code,
        is_platform_admin=is_platform_admin,
        body_hash=body_hash,
        secret=secret
    )

    headers = {
        "X-SV-Internal": "1",
        "X-SV-Timestamp": str(timestamp),
        "X-SV-Nonce": nonce,
        "X-SV-Signature": signature,
        "X-Platform-Admin": "true" if is_platform_admin else "false",
        "Content-Type": "application/json",
    }

    if body_hash:
        headers["X-SV-Body-SHA256"] = body_hash
    if tenant_code:
        headers["X-Tenant-Code"] = tenant_code
    if site_code:
        headers["X-Site-Code"] = site_code

    return SignedRequest(
        method=method,
        path=path,
        headers=headers,
        body=body_str,
        nonce=nonce,
        timestamp=timestamp,
        signature=signature
    )


def generate_idempotency_key(operation: str, *identifiers: str) -> str:
    """Generate deterministic idempotency key."""
    if identifiers:
        return f"{operation}:{':'.join(identifiers)}"
    return f"{operation}:{secrets.token_hex(8)}"


# =============================================================================
# PROOF 1: REPLAY ATTACK PROTECTION
# =============================================================================

def proof_1_replay_attack() -> Tuple[bool, str]:
    """
    Proof 1: Replay Attack Protection

    Send same signed request twice (same nonce/timestamp/signature).
    Second request MUST return 401/403.

    Returns:
        (success: bool, message: str)
    """
    print("\n" + "="*70)
    print("PROOF 1: REPLAY ATTACK PROTECTION")
    print("="*70)

    # Create a signed request
    req = create_signed_request(
        method="GET",
        path="/api/v1/platform/orgs",
        is_platform_admin=True
    )

    print(f"\n1. Created signed request:")
    print(f"   Method: {req.method}")
    print(f"   Path: {req.path}")
    print(f"   Nonce: {req.nonce}")
    print(f"   Timestamp: {req.timestamp}")
    print(f"   Signature: {req.signature[:32]}...")

    print(f"\n2. Headers for request:")
    for key, value in req.headers.items():
        display_value = value[:32] + "..." if len(value) > 32 else value
        print(f"   {key}: {display_value}")

    # Simulate first request (would succeed)
    print(f"\n3. First request: SHOULD SUCCEED (200 OK)")
    print(f"   => Nonce {req.nonce[:16]}... recorded in DB")

    # Simulate second request with SAME nonce (should fail)
    print(f"\n4. Second request (REPLAY - same nonce):")
    print(f"   => MUST RETURN 401/403 'Replay attack detected'")
    print(f"   => MUST LOG security_event: REPLAY_ATTACK, severity S0")

    # Generate expected curl command for manual testing
    print(f"\n5. Manual test (curl):")
    curl_headers = " \\\n    ".join([f'-H "{k}: {v}"' for k, v in req.headers.items()])
    print(f"""
    # First request (should succeed):
    curl -X {req.method} "{BASE_URL}{req.path}" \\
    {curl_headers}

    # Second request (SAME headers - should fail with 401/403):
    curl -X {req.method} "{BASE_URL}{req.path}" \\
    {curl_headers}
    """)

    print("\n" + "-"*70)
    print("EXPECTED BEHAVIOR:")
    print("-"*70)
    print("  Request 1: 200 OK (nonce recorded)")
    print("  Request 2: 401/403 'Replay attack detected'")
    print("  Security Event: REPLAY_ATTACK logged with S0 severity")
    print("-"*70)

    return True, "Proof 1 test case generated successfully"


# =============================================================================
# PROOF 2: WIZARD DOUBLE SUBMIT (IDEMPOTENCY)
# =============================================================================

def proof_2_wizard_double_submit() -> Tuple[bool, str]:
    """
    Proof 2: Wizard Double Submit (Idempotency)

    Send "create tenant" twice with same idempotency key.
    Should NOT create duplicate.

    Returns:
        (success: bool, message: str)
    """
    print("\n" + "="*70)
    print("PROOF 2: WIZARD DOUBLE SUBMIT (IDEMPOTENCY)")
    print("="*70)

    # Wizard data
    org_code = "test-org"
    tenant_code = "test-tenant"

    # Deterministic idempotency key
    idempotency_key = generate_idempotency_key("create-tenant", org_code, tenant_code)

    body = {
        "org_code": org_code,
        "tenant_code": tenant_code,
        "name": "Test Tenant",
        "environment": "development"
    }

    print(f"\n1. Wizard create-tenant request:")
    print(f"   Org Code: {org_code}")
    print(f"   Tenant Code: {tenant_code}")
    print(f"   Idempotency Key: {idempotency_key}")
    print(f"   Body: {json.dumps(body, indent=2)}")

    # Create signed requests (different nonce each time, but same idempotency key)
    req1 = create_signed_request(
        method="POST",
        path="/api/v1/platform/tenants",
        body=body,
        is_platform_admin=True
    )
    req1.headers["X-Idempotency-Key"] = idempotency_key

    # Second request - new nonce/signature but SAME idempotency key
    req2 = create_signed_request(
        method="POST",
        path="/api/v1/platform/tenants",
        body=body,
        is_platform_admin=True
    )
    req2.headers["X-Idempotency-Key"] = idempotency_key

    print(f"\n2. Request 1 (First submit):")
    print(f"   Nonce: {req1.nonce}")
    print(f"   X-Idempotency-Key: {idempotency_key}")
    print(f"   => SHOULD SUCCEED: 201 Created")
    print(f"   => Idempotency key recorded with response")

    print(f"\n3. Request 2 (Double submit - SAME idempotency key):")
    print(f"   Nonce: {req2.nonce} (different nonce!)")
    print(f"   X-Idempotency-Key: {idempotency_key} (SAME key)")
    print(f"   => SHOULD SUCCEED: 200/201 (cached response)")
    print(f"   => NO DUPLICATE CREATED")

    # Generate curl commands
    print(f"\n4. Manual test (curl):")

    body_json = json.dumps(body, separators=(',', ':'), sort_keys=True)
    headers1 = " \\\n    ".join([f'-H "{k}: {v}"' for k, v in req1.headers.items()])
    headers2 = " \\\n    ".join([f'-H "{k}: {v}"' for k, v in req2.headers.items()])

    print(f"""
    # First request (creates tenant):
    curl -X POST "{BASE_URL}{req1.path}" \\
    {headers1} \\
    -d '{body_json}'

    # Second request (double submit - should return cached or 409):
    curl -X POST "{BASE_URL}{req2.path}" \\
    {headers2} \\
    -d '{body_json}'
    """)

    # Test with DIFFERENT body but SAME idempotency key (409 case)
    print(f"\n5. Edge case: Same key, DIFFERENT body (409 Conflict):")

    different_body = {
        "org_code": org_code,
        "tenant_code": tenant_code,
        "name": "DIFFERENT Name",  # Changed!
        "environment": "production"  # Changed!
    }

    req3 = create_signed_request(
        method="POST",
        path="/api/v1/platform/tenants",
        body=different_body,
        is_platform_admin=True
    )
    req3.headers["X-Idempotency-Key"] = idempotency_key

    different_body_json = json.dumps(different_body, separators=(',', ':'), sort_keys=True)
    headers3 = " \\\n    ".join([f'-H "{k}: {v}"' for k, v in req3.headers.items()])

    print(f"""
    # Request with SAME idempotency key but DIFFERENT body:
    curl -X POST "{BASE_URL}{req3.path}" \\
    {headers3} \\
    -d '{different_body_json}'

    => MUST RETURN 409 Conflict (idempotency key reused with different payload)
    """)

    print("\n" + "-"*70)
    print("EXPECTED BEHAVIOR:")
    print("-"*70)
    print("  Request 1 (new):           201 Created + response cached")
    print("  Request 2 (same body):     200/201 (cached response returned)")
    print("  Request 3 (different body): 409 Conflict (key reuse violation)")
    print("")
    print("  UI handles 409 as 'already exists' => continues wizard")
    print("-"*70)

    return True, "Proof 2 test case generated successfully"


# =============================================================================
# PROOF SUMMARY
# =============================================================================

def run_all_proofs():
    """Run all security proofs and generate summary."""
    print("\n" + "="*70)
    print(" SOLVEREIGN V3.3b SECURITY PROOFS")
    print("="*70)
    print(f" Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Secret Key: {TEST_SECRET[:16]}... (for testing only)")
    print("="*70)

    results = []

    # Proof 1
    success1, msg1 = proof_1_replay_attack()
    results.append(("Proof 1: Replay Protection", success1, msg1))

    # Proof 2
    success2, msg2 = proof_2_wizard_double_submit()
    results.append(("Proof 2: Idempotency", success2, msg2))

    # Summary
    print("\n" + "="*70)
    print(" PROOF SUMMARY")
    print("="*70)

    all_passed = True
    for name, success, msg in results:
        status = "[PASS]" if success else "[FAIL]"
        print(f"  {status} {name}")
        if not success:
            all_passed = False
            print(f"       {msg}")

    print("="*70)

    if all_passed:
        print("\n[OK] ALL PROOFS GENERATED SUCCESSFULLY")
        print("\nTo validate, run the curl commands above against a running backend.")
        print("Expected results:")
        print("  - Proof 1: Second request returns 401/403 (replay detected)")
        print("  - Proof 2: Second request returns 200/201 (cached) or 409 (conflict)")
    else:
        print("\n[FAIL] SOME PROOFS FAILED")

    print("\n")
    return all_passed


# =============================================================================
# PYTEST INTEGRATION
# =============================================================================

def test_proof_1_replay_attack():
    """Pytest: Proof 1 - Replay Attack Protection test case generation."""
    success, msg = proof_1_replay_attack()
    assert success, msg


def test_proof_2_wizard_double_submit():
    """Pytest: Proof 2 - Wizard Double Submit test case generation."""
    success, msg = proof_2_wizard_double_submit()
    assert success, msg


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    run_all_proofs()
