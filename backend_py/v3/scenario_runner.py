"""
SOLVEREIGN V3 Scenario Runner
=============================

Parameterized solver runs with side-by-side comparison.
Enables "what-if" analysis for dispatch optimization.

Key Features:
- Multiple solver configs on same forecast
- Seed sweep mode (1-100 seeds)
- Churn calculation vs baseline
- Scenario comparison report
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json
import time as time_module

from .models import (
    SolverConfig,
    ScenarioResult,
    ScenarioComparison,
    PlanStatus,
)
from .compose import get_baseline_plan


# ============================================================================
# Scenario Runner
# ============================================================================

class ScenarioRunner:
    """
    Run multiple solver scenarios on the same forecast.

    Usage:
        runner = ScenarioRunner(db_connection)
        results = runner.run_scenarios(
            forecast_version_id=1,
            scenarios=[
                SolverConfig(seed=42, churn_weight=0.0),
                SolverConfig(seed=42, churn_weight=0.5),
            ],
            labels=["No Churn Penalty", "Churn Penalty 0.5"]
        )
    """

    def __init__(self, db_connection=None, solver_fn=None):
        """
        Initialize scenario runner.

        Args:
            db_connection: Database connection
            solver_fn: Solver function (default: V2 solver)
        """
        self.db = db_connection
        self._solver_fn = solver_fn or self._default_solver

    def run_scenarios(
        self,
        forecast_version_id: int,
        scenarios: list[SolverConfig],
        labels: Optional[list[str]] = None,
        week_key: Optional[str] = None,
        save_to_db: bool = True
    ) -> ScenarioComparison:
        """
        Run multiple scenarios and compare results.

        Args:
            forecast_version_id: Forecast to solve
            scenarios: List of SolverConfig objects
            labels: Optional labels for scenarios (default: config-based)
            week_key: Week key for baseline lookup
            save_to_db: Whether to persist results

        Returns:
            ScenarioComparison with all results
        """
        if labels and len(labels) != len(scenarios):
            raise ValueError("Labels count must match scenarios count")

        # Get baseline for churn calculation
        baseline_plan = None
        baseline_plan_id = None
        if week_key and self.db:
            baseline_plan = get_baseline_plan(week_key, self.db)
            if baseline_plan:
                baseline_plan_id = baseline_plan['id']

        # Run each scenario
        results = []
        for i, config in enumerate(scenarios):
            label = labels[i] if labels else self._generate_label(config)

            result = self._run_single_scenario(
                forecast_version_id=forecast_version_id,
                config=config,
                label=label,
                baseline_plan_id=baseline_plan_id,
                save_to_db=save_to_db,
            )
            results.append(result)

        # Build comparison
        comparison = ScenarioComparison(
            forecast_version_id=forecast_version_id,
            week_key=week_key or "",
            baseline_plan_version_id=baseline_plan_id,
            scenarios=results,
        )

        return comparison

    def run_seed_sweep(
        self,
        forecast_version_id: int,
        base_config: SolverConfig,
        seed_count: int = 10,
        week_key: Optional[str] = None,
        save_to_db: bool = True
    ) -> ScenarioComparison:
        """
        Run solver with multiple seeds to find best result.

        Args:
            forecast_version_id: Forecast to solve
            base_config: Base configuration (seed will be varied)
            seed_count: Number of seeds to try (default 10)
            week_key: Week key for baseline lookup
            save_to_db: Whether to persist results

        Returns:
            ScenarioComparison with all seed results
        """
        scenarios = []
        labels = []

        for seed in range(1, seed_count + 1):
            config = SolverConfig(
                seed=seed,
                weekly_hours_cap=base_config.weekly_hours_cap,
                freeze_window_minutes=base_config.freeze_window_minutes,
                triple_gap_min=base_config.triple_gap_min,
                triple_gap_max=base_config.triple_gap_max,
                split_break_min=base_config.split_break_min,
                split_break_max=base_config.split_break_max,
                churn_weight=base_config.churn_weight,
                seed_sweep_count=1,
                rest_min_minutes=base_config.rest_min_minutes,
                span_regular_max=base_config.span_regular_max,
                span_split_max=base_config.span_split_max,
            )
            scenarios.append(config)
            labels.append(f"Seed {seed}")

        return self.run_scenarios(
            forecast_version_id=forecast_version_id,
            scenarios=scenarios,
            labels=labels,
            week_key=week_key,
            save_to_db=save_to_db,
        )

    def _run_single_scenario(
        self,
        forecast_version_id: int,
        config: SolverConfig,
        label: str,
        baseline_plan_id: Optional[int],
        save_to_db: bool
    ) -> ScenarioResult:
        """
        Run a single scenario.

        Args:
            forecast_version_id: Forecast to solve
            config: Solver configuration
            label: Scenario label
            baseline_plan_id: Baseline plan for churn calculation
            save_to_db: Whether to persist

        Returns:
            ScenarioResult
        """
        start_time = time_module.time()

        # Run solver
        solver_result = self._solver_fn(
            forecast_version_id=forecast_version_id,
            config=config,
            save_to_db=save_to_db,
        )

        solve_time = time_module.time() - start_time

        # Calculate churn vs baseline
        churn_count = 0
        churn_drivers_affected = 0
        churn_percent = 0.0

        if baseline_plan_id and self.db:
            churn = self._calculate_churn(
                baseline_plan_id=baseline_plan_id,
                new_assignments=solver_result.get('assignments', [])
            )
            churn_count = churn['churn_count']
            churn_drivers_affected = churn['drivers_affected']
            churn_percent = churn['churn_percent']

        # Run audits
        audits_passed = solver_result.get('audits_passed', 0)
        audits_total = solver_result.get('audits_total', 7)

        return ScenarioResult(
            plan_version_id=solver_result.get('plan_version_id', 0),
            scenario_label=label,
            forecast_version_id=forecast_version_id,
            baseline_plan_version_id=baseline_plan_id,
            config=config,
            drivers_total=solver_result.get('drivers_total', 0),
            fte_count=solver_result.get('fte_count', 0),
            pt_count=solver_result.get('pt_count', 0),
            avg_weekly_hours=solver_result.get('avg_weekly_hours', 0.0),
            max_weekly_hours=solver_result.get('max_weekly_hours', 0.0),
            churn_count=churn_count,
            churn_drivers_affected=churn_drivers_affected,
            churn_percent=churn_percent,
            audits_passed=audits_passed,
            audits_total=audits_total,
            solve_time_seconds=solve_time,
        )

    def _calculate_churn(
        self,
        baseline_plan_id: int,
        new_assignments: list[dict]
    ) -> dict:
        """
        Calculate churn between baseline and new assignments.

        Churn = number of instance-level changes (added/removed/changed).

        Args:
            baseline_plan_id: Baseline plan ID
            new_assignments: New assignments list

        Returns:
            dict with churn metrics
        """
        if not self.db:
            return {'churn_count': 0, 'drivers_affected': 0, 'churn_percent': 0.0}

        # Fetch baseline assignments
        with self.db.cursor() as cur:
            cur.execute("""
                SELECT driver_id, tour_instance_id, block_id
                FROM assignments
                WHERE plan_version_id = %s
            """, (baseline_plan_id,))

            baseline_rows = cur.fetchall()

        # Build baseline map: tour_instance_id -> (driver_id, block_id)
        baseline_map = {
            row['tour_instance_id']: (row['driver_id'], row['block_id'])
            for row in baseline_rows
        }

        # Build new map
        new_map = {
            a['tour_instance_id']: (a['driver_id'], a['block_id'])
            for a in new_assignments
        }

        # Calculate differences
        all_instances = set(baseline_map.keys()) | set(new_map.keys())
        churn_count = 0
        affected_drivers = set()

        for instance_id in all_instances:
            baseline_val = baseline_map.get(instance_id)
            new_val = new_map.get(instance_id)

            if baseline_val != new_val:
                churn_count += 1

                if baseline_val:
                    affected_drivers.add(baseline_val[0])
                if new_val:
                    affected_drivers.add(new_val[0])

        total_instances = len(all_instances)
        churn_percent = (churn_count / total_instances * 100) if total_instances > 0 else 0.0

        return {
            'churn_count': churn_count,
            'drivers_affected': len(affected_drivers),
            'churn_percent': round(churn_percent, 2),
        }

    def _generate_label(self, config: SolverConfig) -> str:
        """Generate default label from config."""
        parts = [f"seed={config.seed}"]

        if config.churn_weight > 0:
            parts.append(f"churn={config.churn_weight}")

        if config.weekly_hours_cap != 55:
            parts.append(f"cap={config.weekly_hours_cap}h")

        return ", ".join(parts)

    def _default_solver(
        self,
        forecast_version_id: int,
        config: SolverConfig,
        save_to_db: bool
    ) -> dict:
        """
        Default solver wrapper (calls V2 solver).

        Args:
            forecast_version_id: Forecast to solve
            config: Solver configuration
            save_to_db: Whether to persist

        Returns:
            Solver result dict
        """
        # Import here to avoid circular imports
        from .solver_wrapper import solve_forecast

        return solve_forecast(
            forecast_version_id=forecast_version_id,
            seed=config.seed,
            save_to_db=save_to_db,
            solver_config=config,
        )


# ============================================================================
# Scenario Comparison Utilities
# ============================================================================

def compare_scenarios(comparison: ScenarioComparison) -> dict:
    """
    Generate comparison report from scenarios.

    Args:
        comparison: ScenarioComparison object

    Returns:
        Comparison report dict
    """
    if not comparison.scenarios:
        return {'error': 'No scenarios to compare'}

    # Find best scenarios
    valid_scenarios = [
        s for s in comparison.scenarios
        if s.audits_passed == s.audits_total
    ]

    best_drivers = min(valid_scenarios, key=lambda s: s.drivers_total) if valid_scenarios else None
    best_churn = min(valid_scenarios, key=lambda s: s.churn_count) if valid_scenarios else None
    fastest = min(comparison.scenarios, key=lambda s: s.solve_time_seconds)

    return {
        'total_scenarios': len(comparison.scenarios),
        'valid_scenarios': len(valid_scenarios),
        'invalid_scenarios': len(comparison.scenarios) - len(valid_scenarios),
        'best_by_drivers': {
            'label': best_drivers.scenario_label if best_drivers else None,
            'drivers': best_drivers.drivers_total if best_drivers else None,
            'plan_id': best_drivers.plan_version_id if best_drivers else None,
        },
        'best_by_churn': {
            'label': best_churn.scenario_label if best_churn else None,
            'churn_count': best_churn.churn_count if best_churn else None,
            'churn_percent': best_churn.churn_percent if best_churn else None,
            'plan_id': best_churn.plan_version_id if best_churn else None,
        },
        'fastest': {
            'label': fastest.scenario_label,
            'time_seconds': round(fastest.solve_time_seconds, 2),
        },
        'driver_range': {
            'min': min(s.drivers_total for s in comparison.scenarios),
            'max': max(s.drivers_total for s in comparison.scenarios),
        },
        'scenarios': [
            {
                'label': s.scenario_label,
                'drivers': s.drivers_total,
                'fte': s.fte_count,
                'pt': s.pt_count,
                'churn': s.churn_count,
                'churn_percent': s.churn_percent,
                'audits': f"{s.audits_passed}/{s.audits_total}",
                'valid': s.audits_passed == s.audits_total,
                'time_s': round(s.solve_time_seconds, 2),
            }
            for s in comparison.scenarios
        ],
    }


def format_comparison_table(comparison: ScenarioComparison) -> str:
    """
    Format comparison as ASCII table.

    Args:
        comparison: ScenarioComparison object

    Returns:
        Formatted table string
    """
    report = compare_scenarios(comparison)

    lines = [
        "=" * 80,
        f"SCENARIO COMPARISON - Week {comparison.week_key}",
        f"Forecast: {comparison.forecast_version_id} | Baseline: {comparison.baseline_plan_version_id or 'None'}",
        "=" * 80,
        "",
        f"{'Label':<30} {'Drivers':>8} {'FTE':>6} {'PT':>4} {'Churn':>8} {'Audits':>8} {'Time':>8}",
        "-" * 80,
    ]

    for s in report['scenarios']:
        marker = "✓" if s['valid'] else "✗"
        lines.append(
            f"{s['label']:<30} {s['drivers']:>8} {s['fte']:>6} {s['pt']:>4} "
            f"{s['churn']:>8} {s['audits']:>8} {s['time_s']:>7.1f}s {marker}"
        )

    lines.extend([
        "-" * 80,
        "",
        f"Best by Drivers: {report['best_by_drivers']['label'] or 'N/A'} ({report['best_by_drivers']['drivers'] or 0} drivers)",
        f"Best by Churn:   {report['best_by_churn']['label'] or 'N/A'} ({report['best_by_churn']['churn_count'] or 0} changes)",
        f"Fastest:         {report['fastest']['label']} ({report['fastest']['time_seconds']}s)",
        "",
        "=" * 80,
    ])

    return "\n".join(lines)


# ============================================================================
# Convenience Functions
# ============================================================================

def run_scenario_sweep(
    forecast_version_id: int,
    db_connection,
    week_key: Optional[str] = None,
    seed_count: int = 10,
    churn_weights: Optional[list[float]] = None,
    save_to_db: bool = True
) -> ScenarioComparison:
    """
    Run comprehensive scenario sweep.

    Args:
        forecast_version_id: Forecast to solve
        db_connection: Database connection
        week_key: Week key for baseline
        seed_count: Seeds per churn weight
        churn_weights: Churn weights to test (default: [0.0, 0.25, 0.5])
        save_to_db: Whether to persist

    Returns:
        ScenarioComparison with all results
    """
    if churn_weights is None:
        churn_weights = [0.0, 0.25, 0.5]

    scenarios = []
    labels = []

    for churn_weight in churn_weights:
        for seed in range(1, seed_count + 1):
            config = SolverConfig(seed=seed, churn_weight=churn_weight)
            scenarios.append(config)

            if churn_weight == 0.0:
                labels.append(f"Seed {seed}")
            else:
                labels.append(f"Seed {seed}, Churn {churn_weight}")

    runner = ScenarioRunner(db_connection)
    return runner.run_scenarios(
        forecast_version_id=forecast_version_id,
        scenarios=scenarios,
        labels=labels,
        week_key=week_key,
        save_to_db=save_to_db,
    )


def find_best_scenario(
    comparison: ScenarioComparison,
    priority: str = "drivers"
) -> Optional[ScenarioResult]:
    """
    Find best scenario by priority.

    Args:
        comparison: ScenarioComparison
        priority: "drivers" or "churn"

    Returns:
        Best ScenarioResult or None
    """
    if priority == "drivers":
        return comparison.best_by_drivers()
    elif priority == "churn":
        return comparison.best_by_churn()
    else:
        raise ValueError(f"Unknown priority: {priority}")
