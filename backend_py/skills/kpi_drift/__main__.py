#!/usr/bin/env python3
"""
KPI Drift Detector CLI - Proactive anomaly detection for solver KPIs.

Usage:
    # Check drift against baseline
    python -m backend_py.skills.kpi_drift check --tenant gurkerl --pack roster

    # Check drift from telemetry file
    python -m backend_py.skills.kpi_drift check-telemetry --tenant gurkerl --pack roster

    # Generate drift report
    python -m backend_py.skills.kpi_drift report --tenant gurkerl --since 7d

    # Propose baseline update (dry-run)
    python -m backend_py.skills.kpi_drift propose-baseline --tenant gurkerl --pack roster

    # Accept baseline (requires approval)
    python -m backend_py.skills.kpi_drift accept-baseline --tenant gurkerl --pack roster \
        --approved-by user@example.com --reason "Initial pilot baseline"

Exit codes:
    0: OK - No significant drift (<10%)
    1: WARNING - Drift 10-25%
    2: ALERT - Drift 25-50%
    3: INCIDENT - Drift >50%
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .detector import KPIDriftDetector, DriftLevel, DriftResult
from .baseline import BaselineComputer, BaselineProtection, InsufficientDataError


def main():
    parser = argparse.ArgumentParser(
        description="KPI Drift Detector - Proactive anomaly detection"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check command
    check_parser = subparsers.add_parser("check", help="Check drift for current KPIs")
    check_parser.add_argument("--tenant", required=True, help="Tenant code")
    check_parser.add_argument("--pack", required=True, choices=["routing", "roster"])
    check_parser.add_argument("--output", default="KPI_DRIFT_REPORT.json")
    # KPI values as args (for manual testing)
    check_parser.add_argument("--total-drivers", type=int)
    check_parser.add_argument("--coverage-pct", type=float, default=100.0)
    check_parser.add_argument("--fte-ratio", type=float, default=1.0)
    check_parser.add_argument("--max-weekly-hours", type=float, default=54.0)

    # check-telemetry command
    telemetry_parser = subparsers.add_parser(
        "check-telemetry", help="Check drift from solve telemetry"
    )
    telemetry_parser.add_argument("--tenant", required=True)
    telemetry_parser.add_argument("--pack", required=True, choices=["routing", "roster"])
    telemetry_parser.add_argument("--output", default="KPI_DRIFT_REPORT.json")

    # report command
    report_parser = subparsers.add_parser("report", help="Generate drift report")
    report_parser.add_argument("--tenant", required=True)
    report_parser.add_argument("--pack", choices=["routing", "roster"])
    report_parser.add_argument("--since", default="7d", help="Time range (e.g., 7d, 30d)")
    report_parser.add_argument("--output", default="BASELINE_COMPARISON.md")

    # propose-baseline command
    propose_parser = subparsers.add_parser(
        "propose-baseline", help="Propose baseline update (dry-run)"
    )
    propose_parser.add_argument("--tenant", required=True)
    propose_parser.add_argument("--pack", required=True, choices=["routing", "roster"])
    propose_parser.add_argument("--output", default="baseline_proposal.json")

    # accept-baseline command (requires approval)
    accept_parser = subparsers.add_parser(
        "accept-baseline", help="Accept new baseline (requires APPROVER role)"
    )
    accept_parser.add_argument("--tenant", required=True)
    accept_parser.add_argument("--pack", required=True, choices=["routing", "roster"])
    accept_parser.add_argument(
        "--approved-by", required=True, help="Email of approver (REQUIRED)"
    )
    accept_parser.add_argument(
        "--reason", required=True, help="Reason for baseline update (REQUIRED)"
    )
    accept_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.command == "check":
        exit_code = cmd_check(args)
    elif args.command == "check-telemetry":
        exit_code = cmd_check_telemetry(args)
    elif args.command == "report":
        exit_code = cmd_report(args)
    elif args.command == "propose-baseline":
        exit_code = cmd_propose_baseline(args)
    elif args.command == "accept-baseline":
        exit_code = cmd_accept_baseline(args)
    else:
        exit_code = 1

    sys.exit(exit_code)


def cmd_check(args) -> int:
    """Check drift for manually specified KPIs."""
    print("=" * 60)
    print("KPI DRIFT CHECK")
    print("=" * 60)
    print(f"\nTenant: {args.tenant}")
    print(f"Pack: {args.pack}")

    detector = KPIDriftDetector()

    # Build KPIs from args
    if args.pack == "roster":
        kpis = {
            "total_drivers": args.total_drivers or 145,
            "coverage_pct": args.coverage_pct,
            "fte_ratio": args.fte_ratio,
            "max_weekly_hours": args.max_weekly_hours,
        }
    else:
        kpis = {
            "coverage_pct": args.coverage_pct,
            "tw_violations": 0,
            "routes_used": 12,
            "total_distance_km": 245.5,
        }

    print(f"\nCurrent KPIs: {kpis}")

    result = detector.check_drift(
        tenant_code=args.tenant,
        pack=args.pack,
        current_kpis=kpis,
    )

    _print_result(result)
    _save_result(result, args.output)

    return result.exit_code


def cmd_check_telemetry(args) -> int:
    """Check drift from solve telemetry file."""
    print("=" * 60)
    print("KPI DRIFT CHECK (from telemetry)")
    print("=" * 60)
    print(f"\nTenant: {args.tenant}")
    print(f"Pack: {args.pack}")

    detector = KPIDriftDetector()
    result = detector.check_from_solve_telemetry(
        tenant_code=args.tenant,
        pack=args.pack,
    )

    _print_result(result)
    _save_result(result, args.output)

    return result.exit_code


def cmd_report(args) -> int:
    """Generate human-readable baseline comparison report."""
    print("=" * 60)
    print("BASELINE COMPARISON REPORT")
    print("=" * 60)

    computer = BaselineComputer()
    baseline = computer.load_current_baseline(args.tenant, args.pack or "roster")

    if not baseline:
        print(f"\nNo baseline found for {args.tenant}/{args.pack}")
        return 1

    # Generate markdown report
    report_lines = [
        f"# Baseline Comparison Report",
        f"",
        f"> **Generated**: {datetime.now(timezone.utc).isoformat()}",
        f"> **Tenant**: {args.tenant}",
        f"> **Pack**: {args.pack or 'all'}",
        f"> **Baseline Date**: {baseline.computed_at.isoformat()}",
        f"> **Sample Count**: {baseline.sample_count}",
        f"",
        f"---",
        f"",
        f"## Baseline Metrics",
        f"",
        f"| Metric | Mean | Std Dev | Min | Max | Weight |",
        f"|--------|------|---------|-----|-----|--------|",
    ]

    for name, metric in sorted(baseline.metrics.items()):
        report_lines.append(
            f"| {name} | {metric.mean:.2f} | {metric.std_dev:.2f} | "
            f"{metric.min_value:.2f} | {metric.max_value:.2f} | {metric.weight} |"
        )

    report_lines.extend([
        f"",
        f"---",
        f"",
        f"## Drift Thresholds",
        f"",
        f"| Level | Drift Score | Action |",
        f"|-------|-------------|--------|",
        f"| OK | 0-10% | No action |",
        f"| WARNING | 10-25% | Slack notification |",
        f"| ALERT | 25-50% | Create S2 incident |",
        f"| INCIDENT | >50% | Create S1 + escalation |",
        f"",
        f"---",
        f"",
        f"*Report generated by KPI Drift Detector (Skill 116)*",
    ])

    report = "\n".join(report_lines)

    # Save report
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nReport saved to: {args.output}")
    print("\n" + report)

    return 0


def cmd_propose_baseline(args) -> int:
    """Propose baseline update (dry-run)."""
    print("=" * 60)
    print("BASELINE UPDATE PROPOSAL (dry-run)")
    print("=" * 60)
    print(f"\nTenant: {args.tenant}")
    print(f"Pack: {args.pack}")

    computer = BaselineComputer()

    # For demo, use placeholder KPIs
    if args.pack == "roster":
        new_kpis = {
            "total_drivers": 145,
            "coverage_pct": 100.0,
            "fte_ratio": 1.0,
            "max_weekly_hours": 54,
        }
    else:
        new_kpis = {
            "coverage_pct": 100.0,
            "tw_violations": 0,
            "routes_used": 12,
            "total_distance_km": 245.5,
        }

    proposal = computer.propose_baseline_update(
        tenant_code=args.tenant,
        pack=args.pack,
        new_kpis=new_kpis,
    )

    # Save proposal
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2, default=str)

    print(f"\nProposal saved to: {args.output}")

    if proposal["current"]:
        print("\n--- Diff ---")
        for metric, diff in proposal["diff"].items():
            pct = diff["percent_change"]
            arrow = "^" if pct > 0 else "v" if pct < 0 else "="
            print(f"  {metric}: {diff['old_mean']:.2f} -> {diff['new_mean']:.2f} ({arrow}{abs(pct):.1f}%)")
    else:
        print("\nNo current baseline - this will be the first baseline.")

    print("\n" + "=" * 60)
    print("To accept this baseline, run:")
    print(f"  python -m backend_py.skills.kpi_drift accept-baseline \\")
    print(f"    --tenant {args.tenant} --pack {args.pack} \\")
    print(f'    --approved-by YOUR_EMAIL --reason "Your reason here"')
    print("=" * 60)

    return 0


def cmd_accept_baseline(args) -> int:
    """Accept and persist new baseline."""
    print("=" * 60)
    print("BASELINE ACCEPTANCE")
    print("=" * 60)
    print(f"\nTenant: {args.tenant}")
    print(f"Pack: {args.pack}")
    print(f"Approved by: {args.approved_by}")
    print(f"Reason: {args.reason}")

    if args.dry_run:
        print("\n[DRY-RUN] Would accept baseline but not writing.")
        return 0

    computer = BaselineComputer()
    protection = BaselineProtection()

    # Build new baseline from current state
    if args.pack == "roster":
        new_kpis = {
            "total_drivers": 145,
            "coverage_pct": 100.0,
            "fte_ratio": 1.0,
            "max_weekly_hours": 54,
        }
    else:
        new_kpis = {
            "coverage_pct": 100.0,
            "tw_violations": 0,
            "routes_used": 12,
            "total_distance_km": 245.5,
        }

    try:
        baseline = computer.compute_baseline_from_history(
            tenant_code=args.tenant,
            pack=args.pack,
            historical_kpis=[new_kpis],  # Single sample for demo
        )
    except InsufficientDataError:
        # Create minimal baseline
        from .baseline import MetricBaseline, KPIBaseline
        baseline = KPIBaseline(
            tenant_code=args.tenant,
            pack=args.pack,
            site_code=None,
            sample_count=1,
            computed_at=datetime.now(timezone.utc),
            metrics={
                name: MetricBaseline(
                    name=name,
                    mean=value,
                    std_dev=0,
                    min_value=value,
                    max_value=value,
                    weight=1.0,
                    sample_count=1,
                )
                for name, value in new_kpis.items()
            },
        )

    result = protection.accept_baseline(
        tenant_code=args.tenant,
        pack=args.pack,
        new_baseline=baseline,
        approved_by=args.approved_by,
        reason=args.reason,
    )

    if result["success"]:
        print("\n[OK] Baseline accepted and saved!")
        print(f"   Hash: {result['audit_entry']['new_hash']}")
        print(f"   Audit logged.")
        return 0
    else:
        print(f"\n[FAIL] Baseline rejected: {result['error']}")
        return 1


def _print_result(result: DriftResult) -> None:
    """Print drift result to console."""
    level_marker = {
        DriftLevel.OK: "[OK]",
        DriftLevel.WARNING: "[WARN]",
        DriftLevel.ALERT: "[ALERT]",
        DriftLevel.INCIDENT: "[INCIDENT]",
    }

    print(f"\n--- Result ---")
    print(f"Drift Score: {result.drift_score:.1f}%")
    print(f"Drift Level: {level_marker[result.drift_level]} {result.drift_level.value}")
    print(f"Exit Code: {result.exit_code}")

    if result.top_drifters:
        print(f"\nTop Drifters:")
        for name in result.top_drifters:
            drift = result.metric_drifts.get(name)
            if drift:
                arrow = "^" if drift.direction == "higher" else "v" if drift.direction == "lower" else "="
                print(f"  {name}: {drift.current_value:.2f} (baseline: {drift.baseline_mean:.2f}) {arrow}{abs(drift.percent_change):.1f}%")

    print(f"\nBaseline: {result.baseline_sample_count} samples (computed: {result.baseline_computed_at})")


def _save_result(result: DriftResult, output_path: str) -> None:
    """Save drift result to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    print(f"\nResult saved to: {output_path}")


if __name__ == "__main__":
    main()
