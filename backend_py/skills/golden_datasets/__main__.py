#!/usr/bin/env python3
"""
Golden Dataset Manager CLI - Versioned test fixtures for regression testing.

Usage:
    # List all datasets
    python -m backend_py.skills.golden_datasets list

    # List datasets for specific pack
    python -m backend_py.skills.golden_datasets list --pack routing

    # Validate a single dataset
    python -m backend_py.skills.golden_datasets validate --dataset wien_small --pack routing

    # Run full regression suite
    python -m backend_py.skills.golden_datasets regression --pack routing

    # Run regression for all packs
    python -m backend_py.skills.golden_datasets regression

Exit codes:
    0: PASS - All datasets validated, outputs match expected
    1: FAIL - One or more datasets failed validation
    2: ERROR - Dataset not found or infrastructure issue
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .manager import GoldenDatasetManager, DatasetNotFoundError


def main():
    parser = argparse.ArgumentParser(
        description="Golden Dataset Manager - Versioned test fixtures"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list command
    list_parser = subparsers.add_parser("list", help="List all datasets")
    list_parser.add_argument("--pack", choices=["routing", "roster"])
    list_parser.add_argument("--format", choices=["table", "json"], default="table")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a dataset")
    validate_parser.add_argument("--dataset", required=True)
    validate_parser.add_argument("--pack", required=True, choices=["routing", "roster"])
    validate_parser.add_argument("--output", default="VALIDATION_RESULT.json")

    # regression command
    regression_parser = subparsers.add_parser("regression", help="Run full regression suite")
    regression_parser.add_argument("--pack", choices=["routing", "roster"])
    regression_parser.add_argument("--output", default="REGRESSION_REPORT.md")
    regression_parser.add_argument("--json-output", default="REGRESSION_RESULT.json")

    args = parser.parse_args()

    if args.command == "list":
        exit_code = cmd_list(args)
    elif args.command == "validate":
        exit_code = cmd_validate(args)
    elif args.command == "regression":
        exit_code = cmd_regression(args)
    else:
        exit_code = 2

    sys.exit(exit_code)


def cmd_list(args) -> int:
    """List all datasets."""
    print("=" * 60)
    print("GOLDEN DATASETS")
    print("=" * 60)

    manager = GoldenDatasetManager()
    datasets = manager.list_datasets(args.pack)

    if not datasets:
        print("\nNo datasets found.")
        print("Hint: Create golden_datasets/ directory with dataset manifests.")
        return 0

    if args.format == "json":
        print(json.dumps(datasets, indent=2))
    else:
        print(f"\n{'Name':<25} {'Pack':<10} {'Category':<15} Description")
        print("-" * 80)
        for ds in datasets:
            desc = ds.get("description", "")[:30]
            print(f"{ds['name']:<25} {ds['pack']:<10} {ds['category']:<15} {desc}")

    print(f"\nTotal: {len(datasets)} datasets")
    return 0


def cmd_validate(args) -> int:
    """Validate a single dataset."""
    print("=" * 60)
    print("DATASET VALIDATION")
    print("=" * 60)
    print(f"\nDataset: {args.dataset}")
    print(f"Pack: {args.pack}")

    manager = GoldenDatasetManager()

    try:
        result = manager.validate_dataset(args.dataset, args.pack)
    except DatasetNotFoundError as e:
        print(f"\n[ERROR] {e}")
        return 2

    # Save result
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    # Print result
    print(f"\n--- Result ---")
    status = "[PASS]" if result.passed else "[FAIL]"
    print(f"Status: {status}")
    print(f"Output Hash Match: {result.output_hash_match}")
    print(f"KPI Match: {result.kpi_match}")
    print(f"Audit Match: {result.audit_match}")
    print(f"Solve Duration: {result.solve_duration_ms}ms")

    if result.differences:
        print(f"\nDifferences ({len(result.differences)}):")
        for diff in result.differences:
            print(f"  [{diff.severity.upper()}] {diff.field}")
            print(f"    Expected: {diff.expected}")
            print(f"    Actual: {diff.actual}")

    print(f"\nResult saved to: {args.output}")

    return 0 if result.passed else 1


def cmd_regression(args) -> int:
    """Run full regression suite."""
    print("=" * 60)
    print("REGRESSION SUITE")
    print("=" * 60)

    if args.pack:
        print(f"\nPack: {args.pack}")
    else:
        print("\nPack: all")

    manager = GoldenDatasetManager()
    results = manager.validate_all(args.pack)

    # Generate markdown report
    report = _generate_regression_report(results)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    # Save JSON result
    with open(args.json_output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    # Print summary
    print(f"\n--- Summary ---")
    print(f"Total: {results['total']}")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")
    print(f"Errors: {results['errors']}")

    overall_status = "[PASS]" if results["all_passed"] else "[FAIL]"
    print(f"\nOverall: {overall_status}")

    if results["failed"] > 0 or results["errors"] > 0:
        print("\nFailed/Error datasets:")
        for ds in results["datasets"]:
            if not ds.get("passed", True) or ds.get("error"):
                status = "ERROR" if ds.get("error") else "FAIL"
                print(f"  [{status}] {ds['pack']}/{ds['name']}")
                if ds.get("error"):
                    print(f"         {ds['error']}")

    print(f"\nReport saved to: {args.output}")
    print(f"JSON saved to: {args.json_output}")

    return 0 if results["all_passed"] else 1


def _generate_regression_report(results: dict) -> str:
    """Generate markdown regression report."""
    now = datetime.now(timezone.utc).isoformat()

    report = f"""# Golden Dataset Regression Report

**Generated**: {now}

## Summary

| Metric | Count |
|--------|-------|
| Total Datasets | {results['total']} |
| Passed | {results['passed']} |
| Failed | {results['failed']} |
| Errors | {results['errors']} |

## Result: {'PASS' if results['all_passed'] else 'FAIL'}

## Dataset Details

| Dataset | Pack | Category | Status | Duration |
|---------|------|----------|--------|----------|
"""

    for ds in results.get("datasets", []):
        if ds.get("passed", False):
            status = "PASS"
        elif ds.get("error"):
            status = "ERROR"
        else:
            status = "FAIL"

        duration = f"{ds.get('solve_duration_ms', 0)}ms"
        report += f"| {ds['name']} | {ds['pack']} | {ds.get('category', 'N/A')} | {status} | {duration} |\n"

    if results["failed"] > 0:
        report += "\n## Failed Datasets\n\n"
        for ds in results.get("datasets", []):
            if not ds.get("passed", True) and not ds.get("error"):
                report += f"### {ds['pack']}/{ds['name']}\n\n"
                report += f"Differences: {ds.get('differences', 0)}\n\n"

    if results["errors"] > 0:
        report += "\n## Errors\n\n"
        for ds in results.get("datasets", []):
            if ds.get("error"):
                report += f"### {ds['pack']}/{ds['name']}\n\n"
                report += f"```\n{ds['error']}\n```\n\n"

    report += "\n---\n\n*Generated by Golden Dataset Manager (Skill 115)*\n"

    return report


if __name__ == "__main__":
    main()
