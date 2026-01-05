"""
SOLVEREIGN Parser Robustness Test Suite
========================================

Tests parser against 100 Slack input fixtures.

Goal: 0 False Positives - prefer FAIL over "best effort"

Usage:
    python -m tests.test_parser_robustness
    python tests/test_parser_robustness.py

Output:
    tests/reports/parser_report.json
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from v3.parser import parse_tour_line, ParseStatus


def load_fixtures() -> list[dict]:
    """Load test fixtures from JSON file."""
    fixtures_path = Path(__file__).parent / "fixtures" / "slack" / "parser_fixtures.json"

    if not fixtures_path.exists():
        raise FileNotFoundError(f"Fixtures file not found: {fixtures_path}")

    with open(fixtures_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return data['fixtures']


def run_single_test(fixture: dict) -> dict:
    """
    Run parser on single fixture and compare to expected.

    Returns:
        dict with test result details
    """
    fixture_id = fixture['id']
    input_text = fixture['input']
    expected_status = fixture['expect']

    # Run parser
    try:
        result = parse_tour_line(input_text, line_no=fixture_id)
        actual_status = result.parse_status.value
        issues = [{"code": i.code, "message": i.message, "severity": i.severity} for i in result.issues]

        # Check if status matches
        passed = actual_status == expected_status

        # Check specific fail/warn codes if specified
        if 'fail_code' in fixture and expected_status == 'FAIL':
            error_codes = [i['code'] for i in issues if i['severity'] == 'ERROR']
            if fixture['fail_code'] not in error_codes:
                passed = False

        if 'warn_code' in fixture and expected_status == 'WARN':
            warn_codes = [i['code'] for i in issues if i['severity'] == 'WARNING']
            if fixture['warn_code'] not in warn_codes:
                passed = False

        return {
            "id": fixture_id,
            "category": fixture.get('cat', 'unknown'),
            "input": input_text,
            "expected": expected_status,
            "actual": actual_status,
            "passed": passed,
            "issues": issues,
            "canonical": result.canonical_text if result.canonical_text else None,
            "note": fixture.get('note'),
            "error": None
        }

    except Exception as e:
        return {
            "id": fixture_id,
            "category": fixture.get('cat', 'unknown'),
            "input": input_text,
            "expected": expected_status,
            "actual": "EXCEPTION",
            "passed": False,
            "issues": [],
            "canonical": None,
            "note": fixture.get('note'),
            "error": str(e)
        }


def generate_report(results: list[dict]) -> dict:
    """Generate summary report from test results."""
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    failed = sum(1 for r in results if not r['passed'])

    # Group by category
    by_category = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for r in results:
        cat = r['category']
        by_category[cat]['total'] += 1
        if r['passed']:
            by_category[cat]['passed'] += 1
        else:
            by_category[cat]['failed'] += 1

    # Count error codes
    error_codes = defaultdict(int)
    for r in results:
        for issue in r['issues']:
            if issue['severity'] == 'ERROR':
                error_codes[issue['code']] += 1

    # False positives (expected FAIL but got PASS)
    false_positives = [r for r in results if r['expected'] == 'FAIL' and r['actual'] == 'PASS']

    # False negatives (expected PASS but got FAIL)
    false_negatives = [r for r in results if r['expected'] == 'PASS' and r['actual'] == 'FAIL']

    # Wrong warnings (expected WARN but got something else)
    wrong_warnings = [r for r in results if r['expected'] == 'WARN' and r['actual'] != 'WARN']

    report = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "fixtures_file": "tests/fixtures/slack/parser_fixtures.json",
            "version": "1.0.0"
        },
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(100 * passed / total, 1) if total > 0 else 0
        },
        "by_category": dict(by_category),
        "error_codes": dict(error_codes),
        "critical_issues": {
            "false_positives": len(false_positives),
            "false_positives_ids": [r['id'] for r in false_positives],
            "false_negatives": len(false_negatives),
            "false_negatives_ids": [r['id'] for r in false_negatives],
            "wrong_warnings": len(wrong_warnings),
            "wrong_warnings_ids": [r['id'] for r in wrong_warnings]
        },
        "failed_tests": [
            {
                "id": r['id'],
                "input": r['input'],
                "expected": r['expected'],
                "actual": r['actual'],
                "note": r['note'],
                "error": r['error']
            }
            for r in results if not r['passed']
        ]
    }

    return report


def save_report(report: dict, results: list[dict]):
    """Save report to JSON file."""
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)

    # Save summary report
    report_path = reports_dir / "parser_report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Save full results
    full_results_path = reports_dir / "parser_full_results.json"
    with open(full_results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return report_path, full_results_path


def print_summary(report: dict):
    """Print summary to console."""
    print("=" * 70)
    print("SOLVEREIGN Parser Robustness Test Results")
    print("=" * 70)
    print()

    summary = report['summary']
    print(f"Total Tests:    {summary['total']}")
    print(f"Passed:         {summary['passed']}")
    print(f"Failed:         {summary['failed']}")
    print(f"Pass Rate:      {summary['pass_rate']}%")
    print()

    print("By Category:")
    for cat, stats in report['by_category'].items():
        status = "OK" if stats['failed'] == 0 else "FAIL"
        print(f"  {cat:12} {stats['passed']:3}/{stats['total']:3} [{status}]")
    print()

    critical = report['critical_issues']
    if critical['false_positives'] > 0:
        print(f"[CRITICAL] False Positives: {critical['false_positives']} (IDs: {critical['false_positives_ids']})")
    if critical['false_negatives'] > 0:
        print(f"[WARNING] False Negatives: {critical['false_negatives']} (IDs: {critical['false_negatives_ids']})")
    if critical['wrong_warnings'] > 0:
        print(f"[WARNING] Wrong Warnings: {critical['wrong_warnings']} (IDs: {critical['wrong_warnings_ids']})")

    if critical['false_positives'] == 0:
        print("[OK] No False Positives - Parser correctly rejects invalid input")

    print()

    if report['failed_tests']:
        print("Failed Tests Details:")
        for test in report['failed_tests'][:10]:  # Show first 10
            print(f"  #{test['id']}: '{test['input']}'")
            print(f"       Expected: {test['expected']}, Got: {test['actual']}")
            if test['note']:
                print(f"       Note: {test['note']}")
            if test['error']:
                print(f"       Error: {test['error']}")
        if len(report['failed_tests']) > 10:
            print(f"  ... and {len(report['failed_tests']) - 10} more")

    print()
    print("=" * 70)


def main():
    """Run all parser robustness tests."""
    print("Loading fixtures...")
    fixtures = load_fixtures()
    print(f"Loaded {len(fixtures)} fixtures")

    print("Running tests...")
    results = []
    for fixture in fixtures:
        result = run_single_test(fixture)
        results.append(result)

        # Progress indicator
        if result['passed']:
            sys.stdout.write('.')
        else:
            sys.stdout.write('F')
        sys.stdout.flush()

    print()  # Newline after progress dots

    print("Generating report...")
    report = generate_report(results)

    report_path, full_path = save_report(report, results)
    print(f"Report saved to: {report_path}")
    print(f"Full results saved to: {full_path}")

    print()
    print_summary(report)

    # Return exit code based on pass rate
    if report['summary']['pass_rate'] >= 90:
        print("[PASS] Parser robustness test PASSED (>= 90%)")
        return 0
    else:
        print("[FAIL] Parser robustness test FAILED (< 90%)")
        return 1


if __name__ == '__main__':
    sys.exit(main())
