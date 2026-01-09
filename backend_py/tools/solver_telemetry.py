#!/usr/bin/env python3
"""
Solver Telemetry - Capture and persist solver performance metrics.

This module provides utilities to:
1. Capture solve_time, peak_rss, and other metrics from solver runs
2. Write metrics to .claude/telemetry/solve_latest.json
3. Update drift-baselines.json when metrics exceed thresholds

Usage:
    from backend_py.tools.solver_telemetry import SolverTelemetry

    telemetry = SolverTelemetry()
    with telemetry.track_solve("my-solve-run"):
        # ... run solver ...
        pass

    # Or manually:
    telemetry.record_solve(
        solve_time_s=45.2,
        peak_rss_mb=2048,
        tenant_id="gurkerl",
        scenario_id="weekly-001"
    )
"""

import json
import os
import resource
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Platform-specific memory tracking
def get_peak_rss_mb() -> float:
    """Get peak RSS memory usage in MB."""
    if sys.platform == "win32":
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().peak_wset / (1024 * 1024)
        except ImportError:
            return 0.0
    else:
        # Unix: use resource module
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return usage.ru_maxrss / 1024  # Convert KB to MB on Linux


@dataclass
class SolveMetrics:
    """Metrics from a single solve run."""
    solve_time_s: float
    peak_rss_mb: float
    tenant_id: Optional[str] = None
    scenario_id: Optional[str] = None
    label: Optional[str] = None
    seed: Optional[int] = None
    drivers_total: Optional[int] = None
    coverage_percent: Optional[float] = None
    audits_passed: Optional[int] = None
    audits_total: Optional[int] = None
    timestamp: Optional[str] = None
    git_sha: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class SolverTelemetry:
    """
    Capture and persist solver performance metrics.

    Writes to:
    - .claude/telemetry/solve_latest.json (latest run)
    - .claude/telemetry/solve_history.jsonl (append-only history)
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize telemetry writer."""
        if repo_root is None:
            # Find repo root by looking for .claude directory
            current = Path(__file__).parent.parent.parent
            if (current / ".claude").exists():
                repo_root = current
            else:
                repo_root = Path.cwd()

        self.repo_root = repo_root
        self.telemetry_dir = repo_root / ".claude" / "telemetry"
        self.state_dir = repo_root / ".claude" / "state"

        # Ensure directories exist
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def track_solve(self, label: str = "solve", **extra_fields):
        """
        Context manager to track solve time and memory.

        Usage:
            with telemetry.track_solve("my-solve") as metrics:
                # ... run solver ...
                metrics.drivers_total = 145
                metrics.coverage_percent = 100.0

        Args:
            label: Label for this solve run
            **extra_fields: Additional fields to include

        Yields:
            SolveMetrics object to populate with results
        """
        start_time = time.perf_counter()
        start_rss = get_peak_rss_mb()

        metrics = SolveMetrics(
            solve_time_s=0.0,
            peak_rss_mb=0.0,
            label=label,
            **extra_fields
        )

        try:
            yield metrics
        finally:
            end_time = time.perf_counter()
            end_rss = get_peak_rss_mb()

            metrics.solve_time_s = round(end_time - start_time, 3)
            metrics.peak_rss_mb = round(max(end_rss - start_rss, end_rss), 1)

            # Auto-record
            self._write_latest(metrics)
            self._append_history(metrics)

    def record_solve(
        self,
        solve_time_s: float,
        peak_rss_mb: float,
        **extra_fields
    ) -> SolveMetrics:
        """
        Manually record solve metrics.

        Args:
            solve_time_s: Solve time in seconds
            peak_rss_mb: Peak RSS memory in MB
            **extra_fields: Additional fields

        Returns:
            SolveMetrics object
        """
        metrics = SolveMetrics(
            solve_time_s=round(solve_time_s, 3),
            peak_rss_mb=round(peak_rss_mb, 1),
            **extra_fields
        )

        self._write_latest(metrics)
        self._append_history(metrics)

        return metrics

    def _write_latest(self, metrics: SolveMetrics) -> None:
        """Write metrics to solve_latest.json."""
        latest_path = self.telemetry_dir / "solve_latest.json"
        data = asdict(metrics)

        # Add git SHA if available
        if metrics.git_sha is None:
            data["git_sha"] = self._get_git_sha()

        latest_path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8"
        )

    def _append_history(self, metrics: SolveMetrics) -> None:
        """Append metrics to solve_history.jsonl."""
        history_path = self.telemetry_dir / "solve_history.jsonl"
        data = asdict(metrics)

        # Add git SHA if not present
        if metrics.git_sha is None:
            data["git_sha"] = self._get_git_sha()

        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def check_drift(self, metrics: SolveMetrics) -> dict:
        """
        Check if metrics have drifted from baseline.

        Args:
            metrics: Current solve metrics

        Returns:
            Drift report dict
        """
        baselines_path = self.state_dir / "drift-baselines.json"

        try:
            with open(baselines_path, encoding="utf-8") as f:
                baselines = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"status": "no_baseline", "drift": {}}

        drift = {}
        warnings = []

        # Check solver p95 (solve_time)
        baseline_solver = baselines.get("solver_p95_s", 45)
        if metrics.solve_time_s > baseline_solver * 1.25:  # 25% drift
            drift["solver_time"] = {
                "baseline": baseline_solver,
                "current": metrics.solve_time_s,
                "drift_percent": round((metrics.solve_time_s / baseline_solver - 1) * 100, 1)
            }
            warnings.append(f"solve_time drifted +{drift['solver_time']['drift_percent']}%")

        # Check peak RSS
        baseline_rss = baselines.get("solver_peak_rss_mb", 2048)
        if metrics.peak_rss_mb > baseline_rss * 1.25:  # 25% drift
            drift["peak_rss"] = {
                "baseline": baseline_rss,
                "current": metrics.peak_rss_mb,
                "drift_percent": round((metrics.peak_rss_mb / baseline_rss - 1) * 100, 1)
            }
            warnings.append(f"peak_rss drifted +{drift['peak_rss']['drift_percent']}%")

        return {
            "status": "drift_detected" if drift else "ok",
            "drift": drift,
            "warnings": warnings,
        }

    def update_baseline(self, metrics: SolveMetrics) -> None:
        """
        Update drift baselines with current metrics.

        Only call this after a validated golden run.

        Args:
            metrics: Metrics to use as new baseline
        """
        baselines_path = self.state_dir / "drift-baselines.json"

        try:
            with open(baselines_path, encoding="utf-8") as f:
                baselines = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            baselines = {}

        baselines["solver_p95_s"] = metrics.solve_time_s
        baselines["solver_peak_rss_mb"] = metrics.peak_rss_mb
        baselines["last_updated"] = datetime.now(timezone.utc).isoformat()

        baselines_path.write_text(
            json.dumps(baselines, indent=2),
            encoding="utf-8"
        )

    def _get_git_sha(self) -> str:
        """Get current git commit SHA."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.repo_root
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"


# Convenience function for quick recording
def record_solve_metrics(
    solve_time_s: float,
    peak_rss_mb: float,
    **extra_fields
) -> SolveMetrics:
    """
    Convenience function to record solve metrics.

    Args:
        solve_time_s: Solve time in seconds
        peak_rss_mb: Peak RSS memory in MB
        **extra_fields: Additional fields

    Returns:
        SolveMetrics object
    """
    telemetry = SolverTelemetry()
    return telemetry.record_solve(solve_time_s, peak_rss_mb, **extra_fields)


if __name__ == "__main__":
    # Demo usage
    telemetry = SolverTelemetry()

    print("Recording demo solve metrics...")
    metrics = telemetry.record_solve(
        solve_time_s=45.2,
        peak_rss_mb=2048,
        tenant_id="demo",
        scenario_id="test-001",
        drivers_total=145,
        coverage_percent=100.0,
        audits_passed=7,
        audits_total=7,
    )

    print(f"Recorded: {metrics}")

    # Check drift
    drift_report = telemetry.check_drift(metrics)
    print(f"Drift check: {drift_report}")
