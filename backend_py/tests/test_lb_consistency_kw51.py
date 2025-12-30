import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.services.lower_bound_calc import compute_lower_bounds_wrapper
from src.services.instance_profiler import FeatureVector

class TestLBConsistencyKW51(unittest.TestCase):
    """
    Task A: Verify Lower Bound Consistency between Fleet Counter and Solver.
    """

    def test_lower_bound_wrapper_unifies_values(self):
        """
        Test that compute_lower_bounds_wrapper correctly aggregates 
        fleet_peak, hours_lb, and graph_lb into final_lb.
        """
        # Mock blocks (content doesn't matter for this test as we'll mock the internal calculator if needed, 
        # but here we test the wrapper logic aggregation)
        blocks = [] 
        
        # Inputs modeling KW51 scenario
        input_fleet_peak = 169
        input_total_hours = 104 * 55.0 # 5720 hours -> ceil(5720/55) = 104
        
        # Mock internal graph calculation to return 173 (Step 15A result)
        with patch("src.services.lower_bound_calc.LowerBoundCalculator") as MockCalc:
            instance = MockCalc.return_value
            instance.compute_all.return_value = {
                "lb_chain_by_day": {},
                "lb_chain_week": 150,
                "lb_final": 173  # Graph LB
            }
            
            # Capture logs
            logs = []
            def log_fn(msg):
                logs.append(msg)
            
            # Execute
            result = compute_lower_bounds_wrapper(
                blocks, 
                log_fn=log_fn, 
                fleet_peak=input_fleet_peak, 
                total_hours=input_total_hours
            )
            
            # Verify Breakdown
            self.assertEqual(result["fleet_lb"], 169)
            self.assertEqual(result["hours_lb"], 104)
            self.assertEqual(result["graph_lb"], 173)
            
            # Final LB should be max(169, 104, 173) = 173
            self.assertEqual(result["final_lb"], 173)
            
            # Check Log Line Format (Task A Requirement)
            # Logge in D-Search und SP-LB identische Breakdown-Zeile:
            # LB: fleet=..., hours=..., graph=..., final=...
            expected_log_part = "LB] fleet=169, hours=104, graph=173, final=173"
            found_log = any(expected_log_part in line for line in logs)
            self.assertTrue(found_log, f"Log line not found. Logs: {logs}")

    def test_lb_dominance_logic(self):
        """
        Verify final_lb respects the maximum of all inputs.
        """
        blocks = []
        
        scenarios = [
            # Fleet dominates
            {"fleet": 200, "hours": 5500, "graph": 180, "expected": 200},
            # Graph dominates
            {"fleet": 150, "hours": 5500, "graph": 210, "expected": 210},
            # Hours dominates (rare but possible)
            {"fleet": 100, "hours": 11000, "graph": 100, "expected": 200}, # 11000/55 = 200
        ]
        
        with patch("src.services.lower_bound_calc.LowerBoundCalculator") as MockCalc:
            for s in scenarios:
                instance = MockCalc.return_value
                instance.compute_all.return_value = {"lb_final": s["graph"]}
                
                res = compute_lower_bounds_wrapper(
                    blocks, 
                    fleet_peak=s["fleet"], 
                    total_hours=s["hours"]
                )
                self.assertEqual(res["final_lb"], s["expected"], f"Failed for scenario {s}")

if __name__ == "__main__":
    unittest.main()
