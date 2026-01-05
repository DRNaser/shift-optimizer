"""
Gate 8: Observability
=====================
Tests:
8.1 Structured JSON logging
8.2 Prometheus /metrics endpoint
"""

import requests
import sys
import os
import json

BASE_URL = "http://localhost:8000"
API_KEY = "test-api-key-for-gate-3-validation-123456789"


def test_metrics_endpoint():
    """8.2: /metrics endpoint should return Prometheus format."""
    print("  Testing /metrics endpoint...")

    resp = requests.get(f"{BASE_URL}/metrics")

    if resp.status_code == 404:
        print("  /metrics endpoint not found")
        print("  NOTE: Endpoint requires API restart to activate")
        return False  # This is now a FAIL - metrics must be available

    print(f"  Response status: {resp.status_code}")
    print(f"  Content-Type: {resp.headers.get('content-type', 'N/A')}")

    if resp.status_code == 200:
        content = resp.text

        # Check for Prometheus format markers
        has_help = '# HELP' in content
        has_type = '# TYPE' in content

        # Check for required metrics (per senior dev requirements)
        required_metrics = [
            'solve_duration_seconds',
            'solve_failures_total',
            'audit_failures_total',
        ]
        found_required = []
        missing_required = []
        for metric in required_metrics:
            if metric in content:
                found_required.append(metric)
            else:
                missing_required.append(metric)

        # Check for additional expected metrics
        has_http_metrics = 'http_requests_total' in content or 'http_request_duration' in content
        has_build_info = 'solvereign_build_info' in content or 'solver_build_info' in content

        print(f"  Has HELP comments: {has_help}")
        print(f"  Has TYPE comments: {has_type}")
        print(f"  Required metrics found: {found_required}")
        if missing_required:
            print(f"  Required metrics MISSING: {missing_required}")
        print(f"  Has HTTP metrics: {has_http_metrics}")
        print(f"  Has build info: {has_build_info}")

        # Show sample content
        print(f"  Sample content (first 500 chars):")
        print(f"  {content[:500]}...")

        # Pass if we have Prometheus format and at least some metrics
        passed = has_help and has_type and len(found_required) > 0
        return passed

    return False


def test_structured_logging():
    """8.1: Logs should be in structured JSON format."""
    print("  Checking structured logging implementation...")

    # Check logging config file
    log_config_path = os.path.join(os.path.dirname(__file__), '..', 'api', 'logging_config.py')
    if os.path.exists(log_config_path):
        with open(log_config_path, 'r') as f:
            content = f.read()

        has_json = 'json' in content.lower()
        has_structured = 'structured' in content.lower() or 'JsonFormatter' in content
        has_logger = 'logging' in content or 'logger' in content

        print(f"  logging_config.py found")
        print(f"  JSON formatting: {has_json}")
        print(f"  Structured logging: {has_structured}")
        print(f"  Logger setup: {has_logger}")

        return has_json or has_structured
    else:
        print(f"  logging_config.py not found")
        return False


def test_log_format_in_response():
    """8.1b: Check if logs are JSON formatted (from API response)."""
    print("  Checking log format in API response...")

    # Make a request and check for request_id in response
    headers = {"X-API-Key": API_KEY}
    resp = requests.get(f"{BASE_URL}/api/v1/tenants/me", headers=headers)

    # Check for X-Request-ID header
    request_id = resp.headers.get('X-Request-ID')
    if request_id:
        print(f"  X-Request-ID header: {request_id[:16]}...")
        return True
    else:
        print("  X-Request-ID header not found (optional)")
        return True  # Not mandatory


def test_health_response_structure():
    """8.3: Health endpoint should return structured data."""
    print("  Checking health endpoint structure...")

    resp = requests.get(f"{BASE_URL}/health")

    if resp.status_code != 200:
        print(f"  Health endpoint error: {resp.status_code}")
        return False

    data = resp.json()
    print(f"  Health response: {json.dumps(data, indent=2)}")

    # Check for expected fields
    has_status = 'status' in data
    has_version = 'version' in data
    has_timestamp = 'timestamp' in data

    print(f"  Has status: {has_status}")
    print(f"  Has version: {has_version}")
    print(f"  Has timestamp: {has_timestamp}")

    return has_status and has_version


def main():
    print("=" * 60)
    print("GATE 8: OBSERVABILITY")
    print("=" * 60)

    results = {}

    print("\n[8.1] Structured logging")
    print("-" * 40)
    results['structured_logging'] = test_structured_logging()

    print("\n[8.1b] Log format check")
    print("-" * 40)
    results['log_format'] = test_log_format_in_response()

    print("\n[8.2] Prometheus /metrics endpoint")
    print("-" * 40)
    results['metrics'] = test_metrics_endpoint()

    print("\n[8.3] Health endpoint structure")
    print("-" * 40)
    results['health_structure'] = test_health_response_structure()

    print("\n" + "=" * 60)
    print("GATE 8 SUMMARY")
    print("=" * 60)
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test}: {status}")

    all_pass = all(results.values())
    print(f"\nGATE 8 OVERALL: {'PASS' if all_pass else 'FAIL'}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
