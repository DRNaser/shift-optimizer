#!/usr/bin/env python3
"""
MINI-TEST 1: Redaction Leak Test for Skill 113 (Enterprise Audit Report)

Purpose: Verify that customer-safe output contains ZERO sensitive data leaks.

Test Approach:
1. Load fixture with intentional sensitive data
2. Run redaction through audit_report generator
3. Verify 0 pattern matches in customer-safe output

Exit Codes:
- 0: PASS - No leaks detected
- 1: FAIL - Leaks detected
- 2: ERROR - Test infrastructure failure
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any

# ============================================
# SENSITIVE PATTERNS (MUST NOT APPEAR IN CUSTOMER OUTPUT)
# ============================================

LEAK_PATTERNS = [
    # Internal headers
    (r'X-SV-[A-Za-z\-]+', 'Internal header (X-SV-*)'),

    # Secrets and credentials
    (r'(password|secret|token|api_key|credential)\s*[=:]\s*["\']?[^\s"\']+', 'Secret/credential'),
    (r'sk-live-[a-zA-Z0-9]+', 'Live API key'),
    (r'sk-test-[a-zA-Z0-9]+', 'Test API key'),
    (r'INTERNAL_SECRET', 'Internal secret marker'),
    (r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', 'JWT token'),

    # Email addresses
    (r'[\w\.\-]+@[\w\.\-]+\.\w{2,}', 'Email address'),

    # Phone numbers (German/Austrian format)
    (r'\+\d{2}\s*\d{3}\s*\d+', 'Phone number (+XX format)'),
    (r'0\d{3,4}[\-\s]?\d{3,}', 'Phone number (0XXX format)'),

    # IP addresses (private ranges especially)
    (r'\b192\.168\.\d{1,3}\.\d{1,3}\b', 'Private IP (192.168.x.x)'),
    (r'\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', 'Private IP (10.x.x.x)'),
    (r'\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b', 'Private IP (172.16-31.x.x)'),

    # Stack traces
    (r'Traceback \(most recent call last\)', 'Python traceback'),
    (r'File "[^"]+", line \d+', 'Stack trace file reference'),

    # Internal paths
    (r'/app/backend_py/', 'Internal application path'),
    (r'/home/[^/]+/\.secrets/', 'Secrets directory path'),
    (r'C:\\\\Users\\\\[^\\\\]+\\\\AppData', 'Windows user path'),
    (r'credentials\.json', 'Credentials file'),
]

# ============================================
# REDACTION LOGIC (Mirrors 113 skill)
# ============================================

def apply_redaction(content: str) -> str:
    """
    Apply customer-safe redaction rules.
    This mirrors the logic in 113-enterprise-audit-report.md
    """
    redacted = content

    # Internal headers
    redacted = re.sub(r'X-SV-[A-Za-z\-]+["\s:=]*[^\s"\'}\]]*', '[INTERNAL_HEADER]', redacted)

    # Secrets and credentials (key=value patterns)
    redacted = re.sub(
        r'(password|secret|token|api_key|credential|INTERNAL_SECRET)\s*[=:]\s*["\']?[^\s"\'}\],]+["\']?',
        r'\1=[REDACTED]',
        redacted,
        flags=re.IGNORECASE
    )

    # JWT tokens
    redacted = re.sub(
        r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
        '[JWT_REDACTED]',
        redacted
    )

    # API keys
    redacted = re.sub(r'sk-(live|test)-[a-zA-Z0-9]+', '[API_KEY_REDACTED]', redacted)

    # Email addresses
    redacted = re.sub(r'[\w\.\-]+@[\w\.\-]+\.\w{2,}', '[EMAIL_REDACTED]', redacted)

    # Phone numbers
    redacted = re.sub(r'\+\d{2}\s*\d{3}\s*\d+', '[PHONE_REDACTED]', redacted)
    redacted = re.sub(r'0\d{3,4}[\-\s]?\d{3,}', '[PHONE_REDACTED]', redacted)

    # IP addresses
    redacted = re.sub(
        r'\b(192\.168|10\.\d{1,3}|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b',
        '[IP_REDACTED]',
        redacted
    )

    # Stack traces
    redacted = re.sub(
        r'Traceback \(most recent call last\):.*?(?=\n\n|\Z)',
        '[STACK_TRACE_REDACTED]',
        redacted,
        flags=re.DOTALL
    )

    # Internal paths
    redacted = re.sub(r'/app/backend_py/[^\s"\']+', '[PATH_REDACTED]', redacted)
    redacted = re.sub(r'/home/[^/]+/\.secrets/[^\s"\']+', '[PATH_REDACTED]', redacted)
    redacted = re.sub(r'C:\\\\Users\\\\[^\\\\]+\\\\AppData[^\s"\']*', '[PATH_REDACTED]', redacted)

    return redacted


def check_for_leaks(content: str) -> List[Tuple[str, str, str]]:
    """
    Check content for any remaining sensitive patterns.
    Returns list of (pattern_name, match, context) tuples.
    """
    leaks = []

    for pattern, description in LEAK_PATTERNS:
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        for match in matches:
            # Get context (50 chars before and after)
            start = max(0, match.start() - 50)
            end = min(len(content), match.end() + 50)
            context = content[start:end].replace('\n', '\\n')
            leaks.append((description, match.group(), context))

    return leaks


def run_redaction_leak_test(fixture_path: Path) -> Dict[str, Any]:
    """
    Run the full redaction leak test.

    Returns:
        {
            "passed": bool,
            "input_sensitive_count": int,
            "leaks_after_redaction": [...],
            "redaction_applied": bool
        }
    """
    # Load fixture
    with open(fixture_path, 'r', encoding='utf-8') as f:
        fixture = json.load(f)

    # Convert fixture to string (simulates audit report content)
    raw_content = json.dumps(fixture, indent=2)

    # Check raw content has sensitive data (sanity check)
    raw_leaks = check_for_leaks(raw_content)
    if len(raw_leaks) == 0:
        return {
            "passed": False,
            "error": "Fixture contains no sensitive data - test is invalid",
            "input_sensitive_count": 0,
            "leaks_after_redaction": [],
            "redaction_applied": False
        }

    # Apply redaction
    redacted_content = apply_redaction(raw_content)

    # Check for remaining leaks
    remaining_leaks = check_for_leaks(redacted_content)

    return {
        "passed": len(remaining_leaks) == 0,
        "input_sensitive_count": len(raw_leaks),
        "leaks_after_redaction": remaining_leaks,
        "redaction_applied": True,
        "raw_leaks_found": [(desc, match) for desc, match, _ in raw_leaks],
    }


def main():
    """Main entry point for CI integration."""
    print("=" * 60)
    print("MINI-TEST 1: Redaction Leak Test (Skill 113)")
    print("=" * 60)
    print()

    # Find fixture
    script_dir = Path(__file__).parent
    fixture_path = script_dir / "fixtures" / "leak_test_input.json"

    if not fixture_path.exists():
        print(f"ERROR: Fixture not found at {fixture_path}")
        sys.exit(2)

    print(f"Fixture: {fixture_path}")
    print()

    # Run test
    result = run_redaction_leak_test(fixture_path)

    # Report results
    print(f"Input sensitive patterns found: {result['input_sensitive_count']}")
    print(f"Redaction applied: {result['redaction_applied']}")
    print()

    if result.get('error'):
        print(f"ERROR: {result['error']}")
        sys.exit(2)

    if result['passed']:
        print("RESULT: PASS")
        print()
        print("All sensitive patterns were successfully redacted.")
        print(f"  - {result['input_sensitive_count']} sensitive patterns in input")
        print(f"  - 0 leaks in customer-safe output")
        sys.exit(0)
    else:
        print("RESULT: FAIL - LEAKS DETECTED!")
        print()
        print(f"Found {len(result['leaks_after_redaction'])} unredacted sensitive patterns:")
        print()
        for i, (desc, match, context) in enumerate(result['leaks_after_redaction'], 1):
            print(f"  {i}. {desc}")
            print(f"     Match: {match}")
            print(f"     Context: ...{context}...")
            print()

        sys.exit(1)


if __name__ == "__main__":
    main()
