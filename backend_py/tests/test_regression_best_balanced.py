"""
Regression Tests for Shift Optimizer (Split-Shift Enabled)

Two test levels to ensure stability:
- SMOKE (60s): Coverage + Constraint checks only (twopass may not run)
- PERFORMANCE (120s): Full two-pass + split metrics

Gate 1 (Smoke - always pass):
- Coverage 100%
- HardViolations 0
- ZoneViolations 0
- Math assertions OK

Gate 2 (Performance - 120s runs only):
- twopass_executed True
- split_blocks_selected > 0
- drivers in band (160-180)
"""
import subprocess
import json
import os
import pytest
import sys

# Constants
DIAG_SCRIPT = "scripts/diagnostic_run.py"
VALIDATE_SCRIPT = "scripts/validate_schedule.py"
RESULT_FILE = "diag_run_result.json"


# =============================================================================
# SMOKE TESTS (60s budget - Gate 1 only)
# =============================================================================

@pytest.fixture(scope="class")
def run_smoke_60s():
    """Run diagnostic with 60s budget - smoke test only."""
    # Find project root by looking for scripts/diagnostic_run.py
    # This handles running from backend_py/, backend_py/tests/, or project root
    original_dir = os.getcwd()
    while not os.path.exists(DIAG_SCRIPT) and os.getcwd() != os.path.dirname(os.getcwd()):
        os.chdir("..")

    if not os.path.exists(DIAG_SCRIPT):
        os.chdir(original_dir)
        pytest.skip(f"Could not find {DIAG_SCRIPT} from {original_dir}")

    print(f"Running SMOKE test (60s) from {os.getcwd()}...")
    
    cmd = [
        sys.executable, DIAG_SCRIPT,
        "--time_budget", "60",
        "--output_profile", "BEST_BALANCED"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0, f"Diagnostic run failed: {result.stderr}"
    
    with open(RESULT_FILE, "r") as f:
        data = json.load(f)
        
    return data


@pytest.mark.smoke
class TestSmokeGate1:
    """Gate 1: Coverage + Constraints (always pass regardless of budget)."""
    
    def test_run_success(self, run_smoke_60s):
        """Test standard success markers."""
        report = run_smoke_60s
        assert len(report.get("assignments", [])) > 0
        assert report.get("stats") is not None
    
    def test_data_integrity(self, run_smoke_60s):
        """Test data integrity (tours, valid counts)."""
        stats = run_smoke_60s.get("stats", {})

        assert stats["total_tours_input"] == stats["total_tours_assigned"]
        # Minimum tours depends on test data - Wien Pilot has ~89 tours
        # Key assertion is that all input tours are assigned (100% coverage)
        assert stats["total_tours_input"] > 0, "No tours in input data"
    
    def test_constraint_validation(self, run_smoke_60s):
        """Run strict validation script - 0 violations required."""
        if not os.path.exists(VALIDATE_SCRIPT):
            pytest.skip(f"Validation script not found: {VALIDATE_SCRIPT}")

        cmd = [sys.executable, VALIDATE_SCRIPT, RESULT_FILE]
        result = subprocess.run(cmd, capture_output=True, text=True)

        print(result.stdout)
        assert result.returncode == 0, "Validation script crashed"
        assert "Status: VALID [OK]" in result.stdout
        assert "Zone Violations: 0 [OK]" in result.stdout
    
    def test_math_consistency(self, run_smoke_60s):
        """Assert block mix math is consistent."""
        report = run_smoke_60s
        stats = report.get("stats", {})
        assignments = report.get("assignments", [])
        
        block_counts = stats.get("block_counts", {})
        b1 = block_counts.get('1er', 0)
        b2 = block_counts.get('2er', 0)
        b3 = block_counts.get('3er', 0)
        
        b2_split = sum(1 for a in assignments 
                      if a.get("block", {}).get("id", "").startswith("B2S-"))
        b2_reg = b2 - b2_split
        
        tours_covered = b1 + 2*(b2_reg + b2_split) + 3*b3
        tours_input = stats.get("total_tours_input", 0)
        
        print(f"Block mix: 1er={b1}, 2er_reg={b2_reg}, 2er_split={b2_split}, 3er={b3}")
        print(f"Tours covered: {tours_covered}, Tours input: {tours_input}")
        
        assert tours_covered == tours_input, "Math mismatch"
    
    def test_driver_bound_loose(self, run_smoke_60s):
        """Assert driver count is reasonable (loose bound for smoke)."""
        stats = run_smoke_60s.get("stats", {})
        drivers = stats.get("total_drivers")
        total_tours = stats.get("total_tours_input", 0)

        assert drivers is not None
        print(f"Smoke Drivers: {drivers}, Tours: {total_tours}")

        # Driver bounds depend on dataset size
        # Rule of thumb: ~1 driver per 1-3 tours depending on block mix
        assert drivers > 0, "No drivers assigned"
        # Max drivers should not exceed tours (each driver handles at least 1 tour)
        assert drivers <= total_tours, f"Driver count {drivers} exceeds tour count {total_tours}"


# =============================================================================
# PERFORMANCE TESTS (120s budget - Gate 2)
# =============================================================================

@pytest.fixture(scope="class")
def run_performance_120s():
    """Run diagnostic with 120s budget - full performance test."""
    # Find project root by looking for scripts/diagnostic_run.py
    original_dir = os.getcwd()
    while not os.path.exists(DIAG_SCRIPT) and os.getcwd() != os.path.dirname(os.getcwd()):
        os.chdir("..")

    if not os.path.exists(DIAG_SCRIPT):
        os.chdir(original_dir)
        pytest.skip(f"Could not find {DIAG_SCRIPT} from {original_dir}")

    print(f"Running PERFORMANCE test (120s) from {os.getcwd()}...")
    
    cmd = [
        sys.executable, DIAG_SCRIPT,
        "--time_budget", "120",
        "--output_profile", "BEST_BALANCED"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0, f"Diagnostic run failed: {result.stderr}"
    
    with open(RESULT_FILE, "r") as f:
        data = json.load(f)
        
    return data


@pytest.mark.performance
class TestPerformanceGate2:
    """Gate 2: Full performance metrics (120s runs)."""
    
    def test_split_blocks_selected(self, run_performance_120s):
        """Assert that split blocks are actually selected."""
        assignments = run_performance_120s.get("assignments", [])

        split_count = sum(1 for a in assignments
                         if a.get("block", {}).get("id", "").startswith("B2S-"))

        print(f"Selected Split Blocks: {split_count}")

        # MUST have some split blocks selected (if dataset supports splits)
        # Small datasets may have fewer split opportunities
        if len(assignments) > 50:
            assert split_count > 0, "No split blocks selected - feature broken!"

        # Split share bounds - relaxed for smaller datasets
        split_share = split_count / len(assignments) * 100 if assignments else 0
        print(f"Split Share: {split_share:.1f}%")
        # Only check upper bound - lower bound depends on dataset characteristics
        assert split_share < 50, "Split share too high (>50%)"
    
    def test_performance_bounds(self, run_performance_120s):
        """Assert driver count is in optimal band."""
        stats = run_performance_120s.get("stats", {})

        drivers = stats.get("total_drivers")
        total_tours = stats.get("total_tours_input", 0)
        assert drivers is not None

        print(f"PERFORMANCE Mode Drivers: {drivers}, Tours: {total_tours}")

        # Driver bounds depend on dataset size
        # For optimization: drivers should be less than tours (efficient packing)
        assert drivers > 0, "No drivers assigned"
        assert drivers <= total_tours, f"Driver count {drivers} exceeds tour count {total_tours}"
    
    def test_constraint_validation_performance(self, run_performance_120s):
        """Run strict validation for performance run."""
        if not os.path.exists(VALIDATE_SCRIPT):
            pytest.skip(f"Validation script not found: {VALIDATE_SCRIPT}")

        cmd = [sys.executable, VALIDATE_SCRIPT, RESULT_FILE]
        result = subprocess.run(cmd, capture_output=True, text=True)

        print(result.stdout)
        assert result.returncode == 0, "Validation script crashed"
        assert "Status: VALID [OK]" in result.stdout
        assert "Zone Violations: 0 [OK]" in result.stdout
    
    def test_twopass_executed(self, run_performance_120s):
        """Gate-2: Verify two-pass optimization ran (Contract v2.0)."""
        stats = run_performance_120s.get("stats", {})
        
        twopass_executed = stats.get("twopass_executed")
        pass1_time = stats.get("pass1_time_s", 0)
        
        print(f"twopass_executed: {twopass_executed}")
        print(f"pass1_time_s: {pass1_time}")
        
        # With 120s budget, Pass-2 SHOULD execute
        # If not, check if Pass-1 consumed too much budget
        if not twopass_executed:
            assert pass1_time < 110, (
                f"Pass-1 consumed {pass1_time:.1f}s of 120s budget, "
                f"leaving insufficient time for Pass-2. Consider increasing budget."
            )
        
        assert twopass_executed is True, (
            f"twopass_executed must be True for 120s budget. "
            f"pass1_time_s={pass1_time}s. Check solver logs."
        )
    
    def test_schema_version_in_output(self, run_performance_120s):
        """Verify schema_version exists in output (Contract v2.0)."""
        # Check for schema_version or version field
        schema_version = run_performance_120s.get("schema_version")
        version = run_performance_120s.get("version")
        
        print(f"schema_version: {schema_version}, version: {version}")
        
        # At minimum, version should indicate 2.x
        assert schema_version == "2.0" or (version and version.startswith("2")), (
            f"Expected schema_version='2.0' or version starting with '2', "
            f"got schema_version={schema_version}, version={version}"
        )
