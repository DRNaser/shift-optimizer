import unittest
from datetime import time
from src.core_v2.model.column import ColumnV2
from src.core_v2.model.duty import DutyV2
from src.core_v2.model.weektype import WeekCategory
from src.core_v2.master.master_lp import MasterLP
from src.core_v2.pricing.spprc import SPPRCPricer
from src.core_v2.pricing.label import Label
from src.domain.models import Weekday

class TestV2Consistency(unittest.TestCase):
    def test_cost_consistency(self):
        # 1. Create Dummy Column (Low Hours -> would trigger penalties in old model)
        # Create a dummy duty
        d1 = DutyV2(
            duty_id="d1", day=0, 
            start_min=600, end_min=900, # 5 hours
            work_min=300, 
            tour_ids=("t1",), 
            span_min=300
        )
        col = ColumnV2.from_duties("c1", [d1], origin="test")
        
        # Verify hours = 5.0 (VERY LOW)
        self.assertEqual(col.hours, 5.0)
        
        # 2. Check Stage 1 Cost (MasterLP)
        # Should be strictly 1.0 despite low hours
        master = MasterLP([], [])
        cost_master = master._compute_cost(col, WeekCategory.NORMAL)
        print(f"MasterLP Cost: {cost_master}")
        self.assertEqual(cost_master, 1.0, "MasterLP Stage-1 Cost must be 1.0 for real columns")
        
        # 3. Check SPPRC Cost
        # Create a Label that corresponds to this column
        # RC = 1.0 - Duals. Let's assume Duals=0 for simplicity of "Base Cost" check.
        # If Duals=0, RC should be 1.0. 
        # The _finalize_rc adds Base Cost + Penalties + Label.reduced_cost.
        # Label.reduced_cost comes from -Duals. 
        # So Base Cost implied by _finalize_rc(0_duals) should be 1.0.
        
        pricer = SPPRCPricer(None, WeekCategory.NORMAL, None)
        
        lab = Label(
            path=("d1",),
            last_duty=d1,
            total_work_min=300,
            days_worked=1,
            reduced_cost=0.0 # Simulating 0 duals
        )
        
        rc_pricing = pricer._finalize_rc(lab)
        print(f"SPPRC RC (Duals=0): {rc_pricing}")
        self.assertEqual(rc_pricing, 1.0, "SPPRC Base Cost must be 1.0 (no penalties)")

    def test_utilization_cost(self):
        # Verify Stage 2 cost DOES include penalties
        d1 = DutyV2(duty_id="d1", day=0, start_min=0, end_min=300, work_min=300, tour_ids=("t1",), span_min=300)
        col = ColumnV2.from_duties("c1", [d1], origin="test")
        
        cost_util = col.cost_utilization(WeekCategory.NORMAL)
        print(f"Utilization Cost (5h): {cost_util}")
        
        # Normal Week:
        # Base: 1.0
        # Singleton: +0.2
        # <35h: +0.5
        # Underutil (38 - 5)*0.1 = 3.3
        # Total expected: 1.0 + 0.2 + 0.5 + 3.3 = 5.0
        self.assertAlmostEqual(cost_util, 5.0, places=2)

if __name__ == "__main__":
    unittest.main()
