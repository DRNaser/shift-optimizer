#!/usr/bin/env python3
"""
SOLVEREIGN V3 - Command Line Interface
========================================

CLI for operational dispatch management.

Commands:
    solvereign ingest <file>     - Parse and ingest forecast file
    solvereign solve <id> [seed] - Solve forecast and run audit
    solvereign lock <id>         - Lock plan for release
    solvereign export <id>       - Export proof pack
    solvereign status            - Show system status
    solvereign simulate <type>   - Run What-If simulations
    solvereign audit verify      - Verify security audit log integrity

Usage:
    python cli.py ingest forecast_kw51.csv
    python cli.py solve 1 --seed 94
    python cli.py lock 1
    python cli.py export 1
    python cli.py status
    python cli.py simulate cost-curve --forecast 1
    python cli.py simulate auto-sweep --forecast 1 --seeds 15
    python cli.py simulate headcount --forecast 1 --target 140
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# Fix Windows encoding for console output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))


def cmd_ingest(args):
    """Ingest a forecast file."""
    from v3.parser import parse_forecast_text
    from v3.db_instances import expand_tour_template

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        return 1

    print(f"📥 Ingesting: {file_path.name}")
    print("=" * 60)

    # Read file
    with open(file_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # Detect and convert CSV format if needed
    if ";" in raw_text and any(day in raw_text.lower() for day in ["montag", "dienstag", "mittwoch"]):
        print("Detected LTS CSV format, converting...")
        from streamlit_app import convert_lts_csv_to_parser_format
        raw_text = convert_lts_csv_to_parser_format(raw_text)

    # Parse
    try:
        result = parse_forecast_text(
            raw_text=raw_text,
            source=file_path.name,
            save_to_db=True
        )
    except Exception as e:
        print(f"ERROR: Parse failed: {e}")
        return 1

    print(f"\nStatus: {result['status']}")
    print(f"Forecast Version ID: {result.get('forecast_version_id', 'N/A')}")
    print(f"Tours parsed: {result.get('tours_count', 0)}")
    print(f"Warnings: {result.get('warn_count', 0)}")

    if result['status'] == 'FAIL':
        print("\n❌ FAIL - Fix errors and retry")
        for error in result.get('errors', [])[:10]:
            print(f"  - {error}")
        return 1

    # Expand instances
    forecast_id = result.get('forecast_version_id')
    if forecast_id:
        print("\nExpanding tour instances...")
        try:
            from v3 import db
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM tours_normalized
                        WHERE forecast_version_id = %s
                    """, (forecast_id,))
                    templates = cur.fetchall()

            for t in templates:
                expand_tour_template(t['id'])

            print(f"✅ Expanded {len(templates)} templates")
        except Exception as e:
            print(f"Warning: Instance expansion failed: {e}")

    print(f"\n✅ Ingestion complete! Forecast ID: {forecast_id}")
    return 0


def cmd_solve(args):
    """Solve a forecast."""
    from v3.solver_wrapper import solve_and_audit

    forecast_id = args.forecast_id
    seed = args.seed or 94

    print(f"🧮 Solving Forecast #{forecast_id} with seed {seed}")
    print("=" * 60)

    try:
        result = solve_and_audit(forecast_id, seed=seed)
    except Exception as e:
        print(f"ERROR: Solve failed: {e}")
        return 1

    plan_id = result.get('plan_version_id')
    kpis = result.get('kpis', {})
    audit = result.get('audit_results', {})

    print(f"\nPlan Version ID: {plan_id}")
    print(f"\nKPIs:")
    print(f"  Total Drivers: {kpis.get('total_drivers', 'N/A')}")
    print(f"  FTE Drivers: {kpis.get('fte_drivers', 'N/A')}")
    print(f"  PT Drivers: {kpis.get('pt_drivers', 'N/A')}")
    print(f"  PT Ratio: {kpis.get('pt_ratio', 0):.1f}%")

    print(f"\nAudit Results:")
    print(f"  Checks Run: {audit.get('checks_run', 0)}")
    print(f"  Checks Passed: {audit.get('checks_passed', 0)}")

    if audit.get('all_passed'):
        print("\n✅ All audit checks PASSED!")
    else:
        print("\n❌ Some audit checks FAILED:")
        for check_name, check_result in audit.get('results', {}).items():
            if check_result.get('status') == 'FAIL':
                print(f"  - {check_name}: {check_result.get('violation_count', 0)} violations")

    print(f"\n✅ Solve complete! Plan ID: {plan_id}")
    return 0


def cmd_lock(args):
    """Lock a plan for release."""
    from v3 import db

    plan_id = args.plan_id
    locked_by = args.locked_by or os.getenv("USER", "cli@solvereign")

    print(f"🔒 Locking Plan #{plan_id}")
    print("=" * 60)

    # Check if can release
    try:
        can_release, blocking = db.can_release(plan_id)
    except Exception as e:
        print(f"ERROR: Cannot check release status: {e}")
        return 1

    if not can_release:
        print("❌ Cannot lock - blocking checks:")
        for check in blocking:
            print(f"  - {check}")
        return 1

    # Lock
    try:
        db.lock_plan_version(plan_id, locked_by)
    except Exception as e:
        print(f"ERROR: Lock failed: {e}")
        return 1

    print(f"✅ Plan #{plan_id} LOCKED by {locked_by}")
    return 0


def cmd_export(args):
    """Export proof pack."""
    from v3.proof_pack import generate_proof_pack_zip
    from v3 import db
    from v3.db_instances import get_assignments_with_instances, get_tour_instances
    from v3.audit_fixed import audit_plan_fixed
    from v3.solver_wrapper import compute_plan_kpis
    import hashlib
    import json

    plan_id = args.plan_id
    output_dir = Path(args.output or "exports")
    output_dir.mkdir(exist_ok=True)

    print(f"📦 Exporting Proof Pack for Plan #{plan_id}")
    print("=" * 60)

    try:
        # Get plan info
        plan = db.get_plan_version(plan_id)
        if not plan:
            print(f"ERROR: Plan #{plan_id} not found")
            return 1

        forecast_id = plan["forecast_version_id"]
        seed = plan["seed"]

        # Get forecast info
        forecast = db.get_forecast_version(forecast_id)
        input_hash = forecast.get("input_hash", "")

        # Get assignments and instances
        assignments = get_assignments_with_instances(plan_id)
        instances = get_tour_instances(forecast_id)

        instance_list = [
            {
                "id": inst["id"],
                "day": inst["day"],
                "start_ts": inst.get("start_ts"),
                "end_ts": inst.get("end_ts"),
                "work_hours": float(inst.get("work_hours", 0)),
            }
            for inst in instances
        ]

        # Run audit
        audit_results = audit_plan_fixed(plan_id, save_to_db=False)

        # Compute KPIs
        kpis = compute_plan_kpis(plan_id)

        # Build metadata
        solver_config = {
            "seed": seed,
            "version": "v3_with_v2_solver",
            "fatigue_rule": "no_consecutive_triples",
            "rest_min": 660,
            "span_regular_max": 840,
            "span_split_max": 960,
        }
        solver_config_hash = hashlib.sha256(
            json.dumps(solver_config, sort_keys=True).encode()
        ).hexdigest()

        metadata = {
            "plan_version_id": plan_id,
            "forecast_version_id": forecast_id,
            "seed": seed,
            "input_hash": input_hash,
            "output_hash": plan.get("output_hash", ""),
            "solver_config_hash": solver_config_hash,
        }

        # Generate ZIP
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = output_dir / f"proof_pack_plan{plan_id}_{timestamp}.zip"

        generate_proof_pack_zip(
            assignments=assignments,
            instances=instance_list,
            audit_results=audit_results,
            kpis=kpis,
            metadata=metadata,
            output_path=str(zip_path)
        )

        print(f"\n✅ Proof Pack exported: {zip_path}")
        print(f"   Size: {zip_path.stat().st_size / 1024:.1f} KB")

    except Exception as e:
        print(f"ERROR: Export failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


def cmd_simulate(args):
    """Run What-If simulations."""
    import json
    from v3.db_instances import get_tour_instances
    from v3.simulation_engine import (
        run_cost_curve, run_max_hours_policy, run_freeze_tradeoff,
        run_driver_friendly_policy, run_patch_chaos, run_sick_call,
        run_headcount_budget, run_tour_cancel, RiskLevel,
        # V3.2 Advanced Scenarios
        run_multi_failure_cascade, run_probabilistic_churn, run_policy_roi_optimizer
    )
    from v3.seed_sweep import auto_seed_sweep, run_seed_sweep

    scenario = args.scenario
    forecast_id = args.forecast
    output_file = args.output

    print(f"🔬 Running Simulation: {scenario}")
    print("=" * 60)

    # Get tour instances
    try:
        instances = get_tour_instances(forecast_id)
        if not instances:
            print(f"ERROR: No instances found for forecast {forecast_id}")
            return 1

        instance_list = [
            {
                "id": inst["id"],
                "day": inst["day"],
                "start_ts": inst.get("start_ts"),
                "end_ts": inst.get("end_ts"),
                "work_hours": float(inst.get("work_hours", 0)),
                "depot": inst.get("depot", "DEFAULT"),
                "skill": inst.get("skill"),
                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                "crosses_midnight": inst.get("crosses_midnight", False),
            }
            for inst in instances
        ]

        print(f"Loaded {len(instance_list)} tour instances\n")

    except Exception as e:
        print(f"ERROR: Failed to load instances: {e}")
        return 1

    result_data = None

    try:
        if scenario == "cost-curve":
            seed = args.seed or 94
            result = run_cost_curve(instance_list, baseline_seed=seed)

            print(f"Baseline: {result.baseline_drivers} drivers\n")
            print("Rule Cost Analysis:")
            print("-" * 50)
            for entry in result.entries:
                savings = f"-{abs(entry.driver_delta)}" if entry.driver_delta < 0 else f"+{entry.driver_delta}"
                print(f"  {entry.rule_name:25} | {savings:>6} drivers")
            print("-" * 50)
            print(f"Risk Score: {result.risk_score.value}")

            result_data = {
                "scenario": "cost-curve",
                "baseline_drivers": result.baseline_drivers,
                "entries": [{"rule": e.rule_name, "delta": e.driver_delta} for e in result.entries],
                "risk_score": result.risk_score.value,
            }

        elif scenario == "max-hours":
            seed = args.seed or 94
            caps = [int(c) for c in args.caps.split(",")] if args.caps else [55, 52, 50, 48]
            result = run_max_hours_policy(instance_list, baseline_seed=seed, caps_to_test=caps)

            print("Max-Hours Policy Analysis:")
            print("-" * 60)
            print(f"{'Cap':>6} | {'Drivers':>8} | {'FTE':>6} | {'PT%':>6} | {'Delta':>6}")
            print("-" * 60)
            for entry in result.entries:
                delta_str = f"+{entry.driver_delta}" if entry.driver_delta > 0 else str(entry.driver_delta)
                print(f"{entry.policy_value:>5}h | {entry.drivers:>8} | {entry.fte_count:>6} | {entry.pt_ratio:>5.1f}% | {delta_str:>6}")
            print("-" * 60)
            print(f"Risk Score: {result.risk_score.value}")

            result_data = {
                "scenario": "max-hours",
                "entries": [
                    {"cap": e.policy_value, "drivers": e.drivers, "fte": e.fte_count, "pt_ratio": e.pt_ratio}
                    for e in result.entries
                ],
                "risk_score": result.risk_score.value,
            }

        elif scenario == "auto-sweep":
            num_seeds = args.seeds or 15
            parallel = not args.sequential

            print(f"Testing {num_seeds} seeds {'(parallel)' if parallel else '(sequential)'}...\n")

            result = auto_seed_sweep(
                instance_list,
                num_seeds=num_seeds,
                parallel=parallel
            )

            print(f"Best Seed: {result.best_seed} ({result.best_drivers} drivers)")
            print(f"Execution Time: {result.execution_time_ms}ms\n")

            print("Top 3 Seeds:")
            print("-" * 70)
            print(f"{'Rank':>4} | {'Seed':>6} | {'Drivers':>8} | {'FTE':>6} | {'PT':>4} | {'1er':>5} | {'3er':>5}")
            print("-" * 70)
            for i, r in enumerate(result.top_3, 1):
                print(f"{i:>4} | {r.seed:>6} | {r.total_drivers:>8} | {r.fte_drivers:>6} | {r.pt_drivers:>4} | {r.block_1er:>5} | {r.block_3er:>5}")
            print("-" * 70)
            print(f"\nRecommendation: {result.recommendation}")

            result_data = {
                "scenario": "auto-sweep",
                "best_seed": result.best_seed,
                "best_drivers": result.best_drivers,
                "seeds_tested": result.seeds_tested,
                "execution_time_ms": result.execution_time_ms,
                "top_3": [
                    {"seed": r.seed, "drivers": r.total_drivers, "fte": r.fte_drivers, "pt": r.pt_drivers}
                    for r in result.top_3
                ],
            }

        elif scenario == "headcount":
            target = args.target or 140
            seed = args.seed or 94

            result = run_headcount_budget(instance_list, target_drivers=target, baseline_seed=seed)

            status = "ACHIEVED" if result.achieved else "NOT ACHIEVED"
            print(f"Target: {target} drivers | Status: {status}")
            print(f"Baseline: {result.baseline_drivers} -> Final: {result.final_drivers}\n")

            if result.relaxations:
                print("Recommended Relaxations:")
                print("-" * 60)
                for r in result.relaxations:
                    print(f"  {r.get('rule', '-'):25} | -{r.get('savings', 0)} drivers | Risk: {r.get('risk', '-')}")
                print("-" * 60)

            print(f"Risk Score: {result.risk_score.value}")
            for rec in result.recommendations:
                print(f"  * {rec}")

            result_data = {
                "scenario": "headcount",
                "target": target,
                "baseline_drivers": result.baseline_drivers,
                "final_drivers": result.final_drivers,
                "achieved": result.achieved,
                "relaxations": result.relaxations,
                "risk_score": result.risk_score.value,
            }

        elif scenario == "tour-cancel":
            num_cancel = args.count or 20
            target_day = args.day

            result = run_tour_cancel(instance_list, num_cancelled=num_cancel, target_day=target_day)

            print(f"Cancelled: {result.cancelled_tours} tours")
            print(f"Drivers freed: {result.drivers_freed}")
            print(f"Churn: {result.reassignment_churn} ({result.churn_rate:.1%})")
            print(f"Risk Score: {result.risk_score.value}")

            result_data = {
                "scenario": "tour-cancel",
                "cancelled_tours": result.cancelled_tours,
                "drivers_freed": result.drivers_freed,
                "churn_rate": result.churn_rate,
                "risk_score": result.risk_score.value,
            }

        elif scenario == "sick-call":
            num_sick = args.count or 5
            target_day = args.day or 1

            result = run_sick_call(instance_list, num_drivers_out=num_sick, target_day=target_day)

            print(f"Drivers out: {result.drivers_out}")
            print(f"Affected tours: {result.affected_tours}")
            print(f"Repair time: {result.repair_time_seconds:.2f}s")
            print(f"New drivers needed: {result.new_drivers_needed}")
            print(f"Churn: {result.churn_rate:.1%}")
            print(f"Audits pass: {result.all_audits_pass}")
            print(f"Risk Score: {result.risk_score.value}")

            result_data = {
                "scenario": "sick-call",
                "drivers_out": result.drivers_out,
                "affected_tours": result.affected_tours,
                "repair_time_seconds": result.repair_time_seconds,
                "new_drivers_needed": result.new_drivers_needed,
                "risk_score": result.risk_score.value,
            }

        # =====================================================================
        # V3.2 ADVANCED SCENARIOS
        # =====================================================================
        elif scenario == "multi-failure":
            num_sick = args.count or 5
            num_cancel = args.tours or 10
            target_day = args.day or 1
            cascade_prob = args.cascade or 0.15

            result = run_multi_failure_cascade(
                num_drivers_out=num_sick,
                num_tours_cancelled=num_cancel,
                target_day=target_day,
                cascade_probability=cascade_prob
            )

            print(f"Multi-Failure Cascade Simulation")
            print("-" * 60)
            print(f"Initial: {num_sick} drivers sick + {num_cancel} tours cancelled")
            print(f"Cascade events: {len(result.cascade_events)}")
            print(f"Total drivers out: {result.drivers_out}")
            print(f"Total tours cancelled: {result.tours_cancelled}")
            print(f"Total affected tours: {result.total_affected_tours}")
            print(f"Churn: {result.total_churn:.1%}")
            print(f"New drivers needed: {result.new_drivers_needed}")
            print(f"Repair time: {result.repair_time_seconds:.1f}s")
            print(f"Cascade probability: {result.probability_of_cascade:.1%}")
            print(f"Best case: {result.best_case_drivers} | Worst case: {result.worst_case_drivers}")
            print(f"Risk Score: {result.risk_score.value}")

            if result.cascade_events:
                print("\nCascade Events:")
                for e in result.cascade_events:
                    print(f"  Round {e['round']}: +{e['new_sick']} sick, +{e['new_cancelled']} cancelled")

            result_data = {
                "scenario": "multi-failure",
                "drivers_out": result.drivers_out,
                "tours_cancelled": result.tours_cancelled,
                "cascade_events": result.cascade_events,
                "total_churn": result.total_churn,
                "new_drivers_needed": result.new_drivers_needed,
                "repair_time_seconds": result.repair_time_seconds,
                "risk_score": result.risk_score.value,
            }

        elif scenario == "prob-churn":
            num_sims = args.sims or 100
            threshold = args.threshold or 0.10
            failure_prob = args.failure_prob or 0.05

            result = run_probabilistic_churn(
                num_simulations=num_sims,
                churn_threshold=threshold,
                failure_probability=failure_prob
            )

            print(f"Probabilistic Churn Forecast (Monte Carlo)")
            print("-" * 60)
            print(f"Simulations: {result.num_simulations}")
            print(f"Failure probability: {failure_prob:.1%}")
            print(f"Mean churn: {result.mean_churn:.2%} ± {result.std_churn:.2%}")
            print(f"P(Churn > {threshold:.0%}): {result.probability_above_threshold:.1%}")
            print(f"Percentiles: 5%={result.percentile_5:.2%}, 50%={result.percentile_50:.2%}, 95%={result.percentile_95:.2%}")
            ci_lo, ci_hi = result.confidence_interval
            print(f"95% Confidence Interval: [{ci_lo:.2%}, {ci_hi:.2%}]")
            print(f"Risk Score: {result.risk_score.value}")

            result_data = {
                "scenario": "prob-churn",
                "num_simulations": result.num_simulations,
                "mean_churn": result.mean_churn,
                "std_churn": result.std_churn,
                "probability_above_threshold": result.probability_above_threshold,
                "percentile_95": result.percentile_95,
                "confidence_interval": result.confidence_interval,
                "risk_score": result.risk_score.value,
            }

        elif scenario == "policy-roi":
            budget = args.budget or 5
            optimize_for = args.optimize or "balanced"
            arbzg_only = not args.no_arbzg
            constraints = ["arbzg_compliant"] if arbzg_only else []

            result = run_policy_roi_optimizer(
                budget_drivers=budget,
                optimize_for=optimize_for,
                constraints=constraints
            )

            opt = result.optimal_combination
            print(f"Policy ROI Optimizer")
            print("-" * 60)
            print(f"Optimization target: {result.optimization_target.upper()}")
            print(f"Budget: ±{budget} drivers")
            print(f"ArbZG constraint: {'Yes' if arbzg_only else 'No'}")
            print()
            print(f"OPTIMAL COMBINATION:")
            print(f"  Policies: {' + '.join(opt.policy_combination) or '(none)'}")
            print(f"  Driver delta: {opt.driver_delta:+d}")
            print(f"  Cost savings: €{opt.cost_savings_eur:,.0f}/year")
            print(f"  Stability impact: {opt.stability_impact:+.0%}")
            print(f"  ROI Score: {opt.roi_score:.1f}")
            print(f"  Risk: {opt.risk_level.value}")
            print()
            print(f"Pareto frontier: {len(result.pareto_frontier)} non-dominated options")
            print(f"Total combinations analyzed: {len(result.all_combinations)}")
            print(f"Risk Score: {result.risk_score.value}")

            result_data = {
                "scenario": "policy-roi",
                "optimal_combination": {
                    "policies": opt.policy_combination,
                    "driver_delta": opt.driver_delta,
                    "cost_savings_eur": opt.cost_savings_eur,
                    "stability_impact": opt.stability_impact,
                    "roi_score": opt.roi_score,
                },
                "pareto_frontier_count": len(result.pareto_frontier),
                "total_combinations": len(result.all_combinations),
                "risk_score": result.risk_score.value,
            }

        else:
            print(f"ERROR: Unknown scenario '{scenario}'")
            print("Available: cost-curve, max-hours, auto-sweep, headcount, tour-cancel, sick-call, multi-failure, prob-churn, policy-roi")
            return 1

        # Export to file if requested
        if output_file and result_data:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2)
            print(f"\n📄 Results exported to: {output_file}")

        print("\n✅ Simulation complete!")
        return 0

    except Exception as e:
        print(f"ERROR: Simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_audit(args):
    """Run audit-related commands."""
    from v3 import db

    if args.audit_command == "verify":
        print("🔐 Verifying Security Audit Log Integrity")
        print("=" * 60)

        start_id = args.start or 1
        limit = args.limit or 10000

        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Call the verify function
                    cur.execute("""
                        SELECT * FROM verify_security_audit_chain(%s, %s)
                    """, (start_id, limit))

                    result = cur.fetchone()

                    if not result:
                        print("No audit log entries found.")
                        return 0

                    is_valid = result["is_valid"]
                    checked_count = result["checked_count"]
                    first_invalid_id = result["first_invalid_id"]

                    print(f"\nChecked entries: {checked_count}")
                    print(f"Start ID: {start_id}")

                    if is_valid:
                        print(f"\n✅ AUDIT CHAIN VALID - No tampering detected")
                        print(f"   All {checked_count} entries have valid hash chain")
                    else:
                        print(f"\n❌ AUDIT CHAIN INVALID - Tampering detected!")
                        print(f"   First invalid entry ID: {first_invalid_id}")
                        print(f"\n   CRITICAL: Investigate immediately!")
                        return 1

                    # Show chain summary
                    cur.execute("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(DISTINCT tenant_id) as tenants,
                            MIN(timestamp) as first_entry,
                            MAX(timestamp) as last_entry,
                            COUNT(*) FILTER (WHERE severity = 'CRITICAL') as critical_count,
                            COUNT(*) FILTER (WHERE severity = 'WARNING') as warning_count
                        FROM security_audit_log
                        WHERE id >= %s
                        LIMIT %s
                    """, (start_id, limit))

                    summary = cur.fetchone()

                    if summary and summary["total"] > 0:
                        print(f"\n📊 Audit Log Summary:")
                        print(f"   Total entries: {summary['total']}")
                        print(f"   Tenants: {summary['tenants']}")
                        print(f"   First entry: {summary['first_entry']}")
                        print(f"   Last entry: {summary['last_entry']}")
                        print(f"   Critical events: {summary['critical_count']}")
                        print(f"   Warning events: {summary['warning_count']}")

        except Exception as e:
            if "does not exist" in str(e):
                print("❌ Security audit log table not found.")
                print("   Run migration: 010_security_layer.sql")
                return 1
            print(f"ERROR: {e}")
            return 1

        return 0

    else:
        print(f"Unknown audit command: {args.audit_command}")
        print("Available: verify")
        return 1


def cmd_status(args):
    """Show system status."""
    from v3 import db

    print("📊 SOLVEREIGN System Status")
    print("=" * 60)

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Forecast versions
                cur.execute("SELECT COUNT(*) as count FROM forecast_versions")
                fv_count = cur.fetchone()["count"]

                # Plan versions
                cur.execute("SELECT COUNT(*) as count FROM plan_versions")
                pv_count = cur.fetchone()["count"]

                # Locked plans
                cur.execute("SELECT COUNT(*) as count FROM plan_versions WHERE status = 'LOCKED'")
                locked_count = cur.fetchone()["count"]

                # Tour instances
                cur.execute("SELECT COUNT(*) as count FROM tour_instances")
                ti_count = cur.fetchone()["count"]

                # Assignments
                cur.execute("SELECT COUNT(*) as count FROM assignments")
                a_count = cur.fetchone()["count"]

                # Latest plan
                cur.execute("""
                    SELECT pv.id, pv.status, pv.created_at, pv.seed,
                           (SELECT COUNT(DISTINCT driver_id) FROM assignments WHERE plan_version_id = pv.id) as drivers
                    FROM plan_versions pv
                    ORDER BY pv.created_at DESC
                    LIMIT 1
                """)
                latest = cur.fetchone()

        print(f"\nDatabase Statistics:")
        print(f"  Forecast Versions: {fv_count}")
        print(f"  Plan Versions: {pv_count}")
        print(f"  Locked Plans: {locked_count}")
        print(f"  Tour Instances: {ti_count}")
        print(f"  Assignments: {a_count}")

        if latest:
            print(f"\nLatest Plan:")
            print(f"  ID: {latest['id']}")
            print(f"  Status: {latest['status']}")
            print(f"  Created: {latest['created_at']}")
            print(f"  Seed: {latest['seed']}")
            print(f"  Drivers: {latest['drivers']}")

        print("\n✅ System operational")

    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="solvereign",
        description="SOLVEREIGN V3 - Dispatch Optimization CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Ingest a forecast file")
    p_ingest.add_argument("file", help="Path to forecast file (CSV or text)")

    # solve
    p_solve = subparsers.add_parser("solve", help="Solve a forecast")
    p_solve.add_argument("forecast_id", type=int, help="Forecast version ID")
    p_solve.add_argument("--seed", type=int, default=94, help="Solver seed (default: 94)")

    # lock
    p_lock = subparsers.add_parser("lock", help="Lock a plan for release")
    p_lock.add_argument("plan_id", type=int, help="Plan version ID")
    p_lock.add_argument("--locked-by", help="Name/email of person locking")

    # export
    p_export = subparsers.add_parser("export", help="Export proof pack")
    p_export.add_argument("plan_id", type=int, help="Plan version ID")
    p_export.add_argument("--output", "-o", help="Output directory (default: exports)")

    # status
    subparsers.add_parser("status", help="Show system status")

    # audit
    p_audit = subparsers.add_parser("audit", help="Security audit commands")
    p_audit.add_argument("audit_command", choices=["verify"], help="Audit sub-command")
    p_audit.add_argument("--start", type=int, default=1, help="Start ID (default: 1)")
    p_audit.add_argument("--limit", type=int, default=10000, help="Max entries to check (default: 10000)")

    # simulate
    p_simulate = subparsers.add_parser("simulate", help="Run What-If simulations")
    p_simulate.add_argument("scenario", choices=[
        "cost-curve", "max-hours", "auto-sweep", "headcount", "tour-cancel", "sick-call",
        # V3.2 Advanced Scenarios
        "multi-failure", "prob-churn", "policy-roi"
    ], help="Simulation scenario type")
    p_simulate.add_argument("--forecast", "-f", type=int, required=True, help="Forecast version ID")
    p_simulate.add_argument("--seed", type=int, default=94, help="Solver seed (default: 94)")
    p_simulate.add_argument("--target", type=int, help="Target driver count (for headcount)")
    p_simulate.add_argument("--seeds", type=int, default=15, help="Number of seeds to test (for auto-sweep)")
    p_simulate.add_argument("--sequential", action="store_true", help="Run sequentially (not parallel)")
    p_simulate.add_argument("--caps", help="Comma-separated hour caps (for max-hours, e.g. 55,52,50,48)")
    p_simulate.add_argument("--count", type=int, help="Count for tour-cancel, sick-call, or multi-failure (drivers)")
    p_simulate.add_argument("--day", type=int, help="Target day (1-6) for tour-cancel, sick-call, or multi-failure")
    p_simulate.add_argument("--output", "-o", help="Output file for JSON export")
    # V3.2 Advanced Scenario Arguments
    p_simulate.add_argument("--tours", type=int, help="Tours cancelled (for multi-failure)")
    p_simulate.add_argument("--cascade", type=float, help="Cascade probability 0.0-0.5 (for multi-failure)")
    p_simulate.add_argument("--sims", type=int, help="Number of simulations (for prob-churn)")
    p_simulate.add_argument("--threshold", type=float, help="Churn threshold 0.0-1.0 (for prob-churn)")
    p_simulate.add_argument("--failure-prob", type=float, help="Base failure probability (for prob-churn)")
    p_simulate.add_argument("--budget", type=int, help="Driver budget +/- (for policy-roi)")
    p_simulate.add_argument("--optimize", choices=["cost", "stability", "balanced"], help="Optimization target (for policy-roi)")
    p_simulate.add_argument("--no-arbzg", action="store_true", help="Allow non-ArbZG options (for policy-roi)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "ingest": cmd_ingest,
        "solve": cmd_solve,
        "lock": cmd_lock,
        "export": cmd_export,
        "status": cmd_status,
        "audit": cmd_audit,
        "simulate": cmd_simulate,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
