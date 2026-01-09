#!/usr/bin/env python3
"""CLI for Impact Preview - Change Impact Analyzer.

Usage:
    python -m backend_py.skills.impact_preview analyze --change-type config --target SOLVER_TIME_LIMIT --new-value 120
    python -m backend_py.skills.impact_preview analyze --change-type pack --target routing --action disable
    python -m backend_py.skills.impact_preview analyze --change-type migration --file backend_py/db/migrations/024_new.sql
    python -m backend_py.skills.impact_preview analyze --change-type code --changed-files "file1.py,file2.py"
    python -m backend_py.skills.impact_preview rollback-plan --change-id CHG_20260107120000

Exit codes:
    0: SAFE - Low risk, proceed with normal approval
    1: CAUTION - Medium risk, review recommended
    2: RISKY - High risk, requires explicit approval
    3: BLOCKED - Critical risk, blocked by policy
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import ChangeImpactAnalyzer, ChangeType, RiskLevel, ImpactResult


# ASCII risk indicators (avoid emoji for Windows encoding)
RISK_INDICATORS = {
    RiskLevel.SAFE: "[OK]",
    RiskLevel.CAUTION: "[!]",
    RiskLevel.RISKY: "[!!]",
    RiskLevel.BLOCKED: "[X]",
}


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Change Impact Analyzer - Enterprise Admin Confidence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze change impact")
    analyze_parser.add_argument(
        "--change-type",
        required=True,
        choices=["config", "pack", "migration", "code"],
        help="Type of change to analyze",
    )
    analyze_parser.add_argument(
        "--target",
        required=True,
        help="Target of change (config key, pack name, file path, or PR ref)",
    )
    analyze_parser.add_argument(
        "--action",
        default="modify",
        help="Action (enable/disable/modify)",
    )
    analyze_parser.add_argument(
        "--new-value",
        help="New value for config changes",
    )
    analyze_parser.add_argument(
        "--changed-files",
        "--file",
        help="Comma-separated list of changed files (for code/migration)",
    )
    analyze_parser.add_argument(
        "--output",
        default="IMPACT_PREVIEW.md",
        help="Output file path",
    )
    analyze_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of markdown",
    )

    # rollback-plan command
    rollback_parser = subparsers.add_parser("rollback-plan", help="Generate rollback plan")
    rollback_parser.add_argument(
        "--change-id",
        required=True,
        help="Change ID from previous analysis",
    )
    rollback_parser.add_argument(
        "--output",
        default="ROLLBACK_PLAN.md",
        help="Output file path",
    )

    # risk-report command
    risk_parser = subparsers.add_parser("risk-report", help="Generate risk report")
    risk_parser.add_argument(
        "--since",
        default="7d",
        help="Time range for report",
    )
    risk_parser.add_argument(
        "--output",
        default="RISK_REPORT.md",
        help="Output file path",
    )

    args = parser.parse_args()

    if args.command == "analyze":
        asyncio.run(run_analyze(args))

    elif args.command == "rollback-plan":
        run_rollback_plan(args)

    elif args.command == "risk-report":
        run_risk_report(args)


async def run_analyze(args):
    """Run impact analysis."""

    # Parse changed files for code/migration changes
    changed_files = None
    if args.changed_files:
        changed_files = [f.strip() for f in args.changed_files.split(",") if f.strip()]

    # Parse new_value
    new_value = args.new_value
    if new_value:
        # Try to parse as JSON/boolean/number
        if new_value.lower() == "true":
            new_value = True
        elif new_value.lower() == "false":
            new_value = False
        else:
            try:
                new_value = json.loads(new_value)
            except json.JSONDecodeError:
                pass  # Keep as string

    # Create analyzer
    analyzer = ChangeImpactAnalyzer()

    # Run analysis
    try:
        result = await analyzer.analyze(
            change_type=ChangeType(args.change_type),
            target=args.target,
            action=args.action,
            new_value=new_value,
            changed_files=changed_files,
        )
    except Exception as e:
        print(f"Error analyzing change: {e}", file=sys.stderr)
        sys.exit(3)

    # Write outputs
    if args.json:
        write_json_output(result, args.output)
    else:
        write_impact_preview(result, args.output)
        write_affected_tenants(result)
        write_risk_matrix(result)

    # Print summary
    print_summary(result, args.output)

    # Exit with appropriate code
    sys.exit(result.exit_code)


def print_summary(result: ImpactResult, output_path: str):
    """Print analysis summary to console."""

    indicator = RISK_INDICATORS[result.risk_level]

    print()
    print("=" * 60)
    print(f"IMPACT ANALYSIS: {result.target}")
    print("=" * 60)
    print(f"Risk Level: {indicator} {result.risk_level.value}")
    print(f"Risk Score: {result.risk_score:.2f}")
    print(f"Affected Tenants: {len(result.affected_tenants)}")
    print(f"Affected Packs: {', '.join(result.affected_packs) or 'None'}")
    print(f"Approval Required: {'YES' if result.approval_required else 'No'}")

    if result.blocking_reason:
        print()
        print(f"BLOCKED: {result.blocking_reason}")

    if result.recommendations:
        print()
        print("Recommendations:")
        for rec in result.recommendations:
            print(f"  - {rec}")

    print()
    print("Outputs:")
    print(f"  - {output_path}")
    print("  - AFFECTED_TENANTS.json")
    print("  - RISK_MATRIX.json")
    print()


def write_impact_preview(result: ImpactResult, output_path: str):
    """Write human-readable impact preview."""

    indicator = RISK_INDICATORS[result.risk_level]

    content = f"""# Impact Preview

**Change ID**: {result.change_id}
**Analyzed At**: {result.analyzed_at.isoformat()}Z

## Summary

| Metric | Value |
|--------|-------|
| Target | {result.target} |
| Action | {result.action} |
| Risk Level | {indicator} {result.risk_level.value} |
| Risk Score | {result.risk_score:.2f} |
| Approval Required | {"Yes" if result.approval_required else "No"} |

## Scope

- **Affected Tenants**: {len(result.affected_tenants)}
- **Affected Sites**: {len(result.affected_sites)}
- **Affected Packs**: {', '.join(result.affected_packs) or 'None'}

### Tenants
{chr(10).join(f'- {t}' for t in result.affected_tenants) or 'None'}

## Risk Matrix

| Severity | Likelihood |
|----------|------------|
| S0 (Critical) | {result.risk_matrix.get('S0', 0):.1%} |
| S1 (High) | {result.risk_matrix.get('S1', 0):.1%} |
| S2 (Medium) | {result.risk_matrix.get('S2', 0):.1%} |
| S3 (Low) | {result.risk_matrix.get('S3', 0):.1%} |

## Recommendations

{chr(10).join(f'{i+1}. {r}' for i, r in enumerate(result.recommendations)) or 'No specific recommendations'}

## Rollback Plan

**Complexity**: {result.rollback_complexity}

{chr(10).join(result.rollback_steps)}

"""

    if result.blocking_reason:
        content += f"""
## BLOCKED

**Reason**: {result.blocking_reason}

This change cannot proceed until the blocking condition is resolved.
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def write_json_output(result: ImpactResult, output_path: str):
    """Write JSON output."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)


def write_affected_tenants(result: ImpactResult):
    """Write affected tenants JSON."""
    with open("AFFECTED_TENANTS.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "change_id": result.change_id,
                "tenants": result.affected_tenants,
                "sites": result.affected_sites,
                "packs": result.affected_packs,
            },
            f,
            indent=2,
        )


def write_risk_matrix(result: ImpactResult):
    """Write risk matrix JSON."""
    with open("RISK_MATRIX.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "change_id": result.change_id,
                "risk_level": result.risk_level.value,
                "risk_score": result.risk_score,
                "matrix": result.risk_matrix,
            },
            f,
            indent=2,
        )


def run_rollback_plan(args):
    """Generate rollback plan from previous analysis."""

    # Try to load previous analysis from IMPACT_PREVIEW.md or RISK_MATRIX.json
    risk_matrix_path = Path("RISK_MATRIX.json")
    if not risk_matrix_path.exists():
        print(f"Error: No previous analysis found for change {args.change_id}", file=sys.stderr)
        print("Run 'analyze' first to create an analysis.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(risk_matrix_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("change_id") != args.change_id:
            print(f"Warning: Loaded analysis is for {data.get('change_id')}, not {args.change_id}")

    except Exception as e:
        print(f"Error loading previous analysis: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating rollback plan for {args.change_id}")
    print(f"Output: {args.output}")

    # Generate a generic rollback plan
    content = f"""# Rollback Plan

**Change ID**: {args.change_id}
**Generated**: {datetime.now(timezone.utc).isoformat()}Z

## Pre-Rollback Checklist

- [ ] Notify affected teams
- [ ] Verify backup exists
- [ ] Confirm rollback window

## Rollback Steps

1. Stop affected services
2. Revert change (see original analysis for specifics)
3. Restart services
4. Verify health endpoints
5. Run smoke tests
6. Confirm with stakeholders

## Post-Rollback Verification

- [ ] Health endpoints responding
- [ ] No error spike in logs
- [ ] Affected tenants confirmed working
"""

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)

    print("Rollback plan generated.")
    sys.exit(0)


def run_risk_report(args):
    """Generate risk report for time range."""

    print(f"Generating risk report for last {args.since}")
    print(f"Output: {args.output}")

    # Generate a placeholder report
    content = f"""# Risk Report

**Generated**: {datetime.now(timezone.utc).isoformat()}Z
**Time Range**: Last {args.since}

## Summary

| Metric | Value |
|--------|-------|
| Changes Analyzed | 0 |
| Blocked | 0 |
| Risky | 0 |
| Caution | 0 |
| Safe | 0 |

## Changes by Type

No changes recorded in this time range.

## Recommendations

1. Continue monitoring change impact
2. Review blocked changes for resolution
3. Update risk thresholds as needed
"""

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)

    print("Risk report generated.")
    sys.exit(0)


if __name__ == "__main__":
    main()
