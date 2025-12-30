import unittest
from dataclasses import dataclass
from src.services.lower_bound_calc import LowerBoundCalculator

@dataclass
class MockBlock:
    block_id: str
    day: str
    start_min: int
    end_min: int

class TestLowerBoundCalculator(unittest.TestCase):
    def test_inday_chaining(self):
        # 3 tours in a chain
        # T1: 08:00-12:00 (480-720)
        # T2: 12:30-16:30 (750-990) -> Gap 30m OK
        # T3: 17:00-21:00 (1020-1260) -> Gap 30m OK
        blocks = [
            MockBlock("T1", "Mon", 480, 720),
            MockBlock("T2", "Mon", 750, 990),
            MockBlock("T3", "Mon", 1020, 1260),
        ]
        calc = LowerBoundCalculator(blocks, min_gap_minutes=30)
        res = calc.compute_all()
        # Should be covered by 1 driver
        self.assertEqual(res["lb_final"], 1)
        self.assertEqual(res["lb_chain_week"], 1)

    def test_inday_overlap(self):
        # 2 tours overlapping
        blocks = [
            MockBlock("T1", "Mon", 480, 720),
            MockBlock("T2", "Mon", 500, 900),
        ]
        calc = LowerBoundCalculator(blocks)
        res = calc.compute_all()
        # Need 2 drivers
        self.assertEqual(res["lb_final"], 2)

    def test_cross_day_rest(self):
        # T1 Mon 08:00-20:00 (End 20:00)
        # T2 Tue 06:00-14:00 (Start 06:00)
        # Rest: 20:00 -> 06:00 next day = 10 hours.
        # Required: 11h.
        # So T1 -> T2 is INVALID.
        blocks = [
            MockBlock("T1", "Mon", 480, 1200), # End 20:00
            MockBlock("T2", "Tue", 360, 840),  # Start 06:00
        ]
        calc = LowerBoundCalculator(blocks, rest_hours=11)
        res = calc.compute_all()
        # Need 2 drivers because T1 cannot flow to T2
        self.assertEqual(res["lb_final"], 2)

    def test_cross_day_rest_ok(self):
        # T1 Mon 08:00-18:00 (End 18:00)
        # T2 Tue 06:00-14:00 (Start 06:00)
        # Rest: 18:00 -> 06:00 = 12 hours. OK.
        blocks = [
            MockBlock("T1", "Mon", 480, 1080), # End 18:00
            MockBlock("T2", "Tue", 360, 840),  # Start 06:00
        ]
        calc = LowerBoundCalculator(blocks, rest_hours=11)
        res = calc.compute_all()
        # 1 driver
        self.assertEqual(res["lb_final"], 1)

if __name__ == '__main__':
    unittest.main()
