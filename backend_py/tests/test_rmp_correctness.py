
import unittest
from ortools.sat.python import cp_model
from src.services.set_partition_master import solve_rmp
from src.services.roster_column import RosterColumn

class TestRMPCorrectness(unittest.TestCase):
    def test_coverage_element_is_tour_id(self):
        """
        Verify that the Master Problem enforces coverage on TOUR_IDs, not Block IDs.
        
        Scenario:
        - 3 Tours: T1, T2, T3
        - Column A covers T1, T2 (Block B1)
        - Column B covers T2, T3 (Block B2)
        - Column C covers T1 (Block B3)
        
        If we cover by BLOCK ID (B1, B2, B3), we just need one column per block? 
        No, usually Set Partitioning is: Each Element must be covered exactly once.
        
        If the elements are TOURS:
        - Constraint T1: Covered by A, C -> y_A + y_C == 1
        - Constraint T2: Covered by A, B -> y_A + y_B == 1
        - Constraint T3: Covered by B    -> y_B == 1
        
        This forces:
        - y_B = 1 (to cover T3) -> Covers T2 as well.
        - Constraint T2: y_A + 1 = 1 => y_A = 0.
        - Constraint T1: 0 + y_C = 1 => y_C = 1.
        
        Solution: Select B and C. (Drivers = 2)
        
        If we solved by BLOCK ID (assuming B1, B2, B3 are the items tol cover):
        - This is ambiguous if we don't know the mapping.
        But the requirement is explicit: "No leftover block_id exactly once".
        
        So we will mock RosterColumns that have `tour_ids` attribute.
        """
        
        # Mock RosterColumns with 'tour_ids'
        # Note: RosterColumn might not have 'tour_ids' yet, we need to add it in Step 2.
        # But we can monkey-patch or subclass for the test if needed, 
        # OR better, we implementing Step 2 (Fix Column Pool) first/parallel.
        # However, the user asked for Step 1 first. 
        # We will assume RosterColumn has a 'covered_tour_ids' field as per Step 2 requirements.
        
        class MockRosterColumn:
            def __init__(self, id, tour_ids, cost=1.0):
                self.roster_id = id
                self.covered_tour_ids = tour_ids
                self.total_minutes = 480 * len(tour_ids) # dummy
                self.num_blocks = len(tour_ids)
                self.block_ids = [f"BLK_{t}" for t in tour_ids] # dummy
                self.day_stats = []
                self.total_hours = self.total_minutes / 60.0
                
        
        col_A = MockRosterColumn("A", ["T1", "T2"])
        col_B = MockRosterColumn("B", ["T2", "T3"])
        col_C = MockRosterColumn("C", ["T1"])
        
        columns = [col_A, col_B, col_C]
        all_tour_ids = {"T1", "T2", "T3"}
        
        # We need to pass 'all_tour_ids' to solve_rmp instead of 'all_block_ids'
        # The current signature is solve_rmp(columns, all_block_ids, ...)
        # We will pass tour_ids as the second argument.
        
        result = solve_rmp(
            columns=columns,
            all_block_ids=all_tour_ids, # INTENTIONALLY passing tour_ids here
            time_limit=5.0,
            coverage_attr="covered_tour_ids"
        )
        
        self.assertEqual(result["status"], "OPTIMAL")
        selected_ids = sorted([c.roster_id for c in result["selected_rosters"]])
        
        # Expect B and C
        self.assertEqual(selected_ids, ["B", "C"], "Should select B and C to cover T1, T2, T3 exactly once.")
        
        # If it selected A:
        # A covers T1, T2.
        # T3 needs coverage -> B covers T2, T3.
        # A + B covers T1 (once), T2 (twice!), T3 (once).
        # This would violate T2 coverage == 1.
        
if __name__ == '__main__':
    unittest.main()
