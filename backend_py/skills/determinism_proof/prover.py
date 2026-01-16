"""
Determinism Prover - Validates solver determinism across multiple runs.

Uses the V3 solver pipeline with the golden dataset (Wien pilot forecast)
to verify that identical seeds produce identical results.
"""

import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from datetime import time as dt_time

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from v3.src_compat.models import Tour, Weekday
    from v3.solver_v2_integration import partition_tours_into_blocks
    from v3.src_compat.block_heuristic_solver import BlockHeuristicSolver
except ImportError as e:
    print(f"Warning: Could not import solver modules: {e}")
    Tour = None
    Weekday = None


# Golden seed (canonical for Wien pilot)
GOLDEN_SEED = 94


@dataclass
class DeterminismResult:
    """Result of a determinism proof run."""
    passed: bool
    unique_hashes: int
    runs_completed: int
    hashes: list[str]
    fte_counts: list[int]
    pt_counts: list[int]
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "unique_hashes": self.unique_hashes,
            "runs_completed": self.runs_completed,
            "hashes": self.hashes,
            "fte_counts": self.fte_counts,
            "pt_counts": self.pt_counts,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class DeterminismProver:
    """
    Proves solver determinism by running multiple iterations.

    Strategy:
    1. Load golden dataset (Wien pilot forecast)
    2. Run solver N times with same seed
    3. Verify all output hashes are identical
    """

    def __init__(self, seed: int = GOLDEN_SEED, verbose: bool = False):
        self.seed = seed
        self.verbose = verbose
        self.forecast_path = self._find_forecast_file()

    def _find_forecast_file(self) -> Optional[Path]:
        """Locate the forecast input CSV file."""
        candidates = [
            # CI fixture location (primary for CI/CD)
            Path(__file__).parent.parent.parent / "tests" / "fixtures" / "forecast_ci_test.csv",
            # Project root locations
            Path(__file__).parent.parent.parent.parent / "forecast input.csv",
            Path(__file__).parent.parent.parent / "forecast input.csv",
            Path.cwd() / "forecast input.csv",
            # Alternative CI paths
            Path.cwd() / "backend_py" / "tests" / "fixtures" / "forecast_ci_test.csv",
        ]
        for path in candidates:
            if path.exists():
                if self.verbose:
                    print(f"[DETERMINISM] Found forecast file: {path}")
                return path
        return None

    def _parse_forecast(self) -> list:
        """Parse German-formatted forecast CSV (supports both formats)."""
        if not self.forecast_path or not self.forecast_path.exists():
            raise FileNotFoundError(f"Forecast file not found. Tried: {self.forecast_path}")

        if Tour is None or Weekday is None:
            raise ImportError("Solver modules not available")

        with open(self.forecast_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.strip().split("\n")

        # Detect format: single-column (day headers) or multi-column
        is_single_column = any(
            line.strip().lower().startswith(day)
            for line in lines[:10]
            for day in ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
        )

        if is_single_column:
            return self._parse_single_column(lines)
        else:
            return self._parse_multi_column(lines)

    def _parse_single_column(self, lines: list) -> list:
        """Parse single-column format with day headers (e.g., 'Montag;Anzahl')."""
        tours = []
        tour_counter = 0
        current_day = None

        day_mapping = {
            "montag": Weekday.MONDAY,
            "dienstag": Weekday.TUESDAY,
            "mittwoch": Weekday.WEDNESDAY,
            "donnerstag": Weekday.THURSDAY,
            "freitag": Weekday.FRIDAY,
            "samstag": Weekday.SATURDAY,
            "sonntag": Weekday.SUNDAY,
        }

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Check for day header
            lower_line = line.lower()
            found_day = False
            for day_name, weekday in day_mapping.items():
                if lower_line.startswith(day_name):
                    current_day = weekday
                    found_day = True
                    break

            if found_day:
                continue

            # Parse time;count row
            if current_day and ";" in line:
                parts = line.split(";")
                if len(parts) >= 2:
                    time_range = parts[0].strip()
                    count_str = parts[1].strip()

                    if "-" in time_range and count_str.isdigit():
                        try:
                            count = int(count_str)
                            if count > 0:
                                start_str, end_str = time_range.split("-")
                                start_h, start_m = map(int, start_str.split(":"))
                                end_h, end_m = map(int, end_str.split(":"))

                                for i in range(count):
                                    tour_counter += 1
                                    tour = Tour(
                                        id=f"T{tour_counter:04d}",
                                        day=current_day,
                                        start_time=dt_time(start_h, start_m),
                                        end_time=dt_time(end_h, end_m),
                                    )
                                    tours.append(tour)
                        except (ValueError, IndexError):
                            pass

        return tours

    def _parse_multi_column(self, lines: list) -> list:
        """Parse multi-column format (6 days in columns)."""
        tours = []
        tour_counter = 0

        column_days = [
            (0, 1, Weekday.MONDAY),
            (2, 3, Weekday.TUESDAY),
            (4, 5, Weekday.WEDNESDAY),
            (6, 7, Weekday.THURSDAY),
            (8, 9, Weekday.FRIDAY),
            (10, 11, Weekday.SATURDAY),
        ]

        for line in lines[1:]:  # Skip header
            line = line.strip()
            if not line:
                continue

            parts = line.split(";")

            for time_col, count_col, weekday in column_days:
                if time_col >= len(parts) or count_col >= len(parts):
                    continue

                time_range = parts[time_col].strip()
                count_str = parts[count_col].strip()

                if not time_range or not count_str or "-" not in time_range:
                    continue

                try:
                    count = int(count_str)
                    if count <= 0:
                        continue

                    start_str, end_str = time_range.split("-")
                    start_h, start_m = map(int, start_str.split(":"))
                    end_h, end_m = map(int, end_str.split(":"))

                    for i in range(count):
                        tour_counter += 1
                        tour = Tour(
                            id=f"T{tour_counter:04d}",
                            day=weekday,
                            start_time=dt_time(start_h, start_m),
                            end_time=dt_time(end_h, end_m),
                        )
                        tours.append(tour)
                except (ValueError, IndexError):
                    continue

        return tours

    def _run_solver(self, tours: list) -> dict:
        """Run V3 solver and return result with hash."""
        # Step 1: Greedy block partitioning
        blocks = partition_tours_into_blocks(tours, seed=self.seed)

        # Step 2: BlockHeuristicSolver
        solver = BlockHeuristicSolver(blocks)
        drivers = solver.solve()

        # Compute metrics
        fte_drivers = [d for d in drivers if d.total_hours >= 40.0]
        pt_drivers = [d for d in drivers if d.total_hours < 40.0]

        # Build determinism hash
        driver_data = sorted([
            (d.id, round(d.total_hours, 2), len(d.blocks))
            for d in drivers
        ])
        determinism_hash = hashlib.sha256(
            json.dumps(driver_data, sort_keys=True).encode()
        ).hexdigest()

        return {
            "hash": determinism_hash,
            "fte_count": len(fte_drivers),
            "pt_count": len(pt_drivers),
            "total_drivers": len(drivers),
        }

    def prove(self, runs: int = 3) -> DeterminismResult:
        """
        Run determinism proof.

        Args:
            runs: Number of solver iterations to run

        Returns:
            DeterminismResult with pass/fail and details
        """
        if self.verbose:
            print(f"[DETERMINISM] Starting {runs} runs with seed={self.seed}")

        try:
            # Parse forecast once
            tours = self._parse_forecast()
            if self.verbose:
                print(f"[DETERMINISM] Loaded {len(tours)} tours from forecast")

            # Run solver multiple times
            hashes = []
            fte_counts = []
            pt_counts = []

            for i in range(runs):
                result = self._run_solver(tours)
                hashes.append(result["hash"])
                fte_counts.append(result["fte_count"])
                pt_counts.append(result["pt_count"])

                if self.verbose:
                    print(f"[DETERMINISM] Run {i+1}: hash={result['hash'][:16]}..., "
                          f"FTE={result['fte_count']}, PT={result['pt_count']}")

            # Check determinism
            unique_hashes = len(set(hashes))
            passed = unique_hashes == 1

            return DeterminismResult(
                passed=passed,
                unique_hashes=unique_hashes,
                runs_completed=runs,
                hashes=hashes,
                fte_counts=fte_counts,
                pt_counts=pt_counts,
            )

        except Exception as e:
            return DeterminismResult(
                passed=False,
                unique_hashes=0,
                runs_completed=0,
                hashes=[],
                fte_counts=[],
                pt_counts=[],
                error=str(e),
            )
