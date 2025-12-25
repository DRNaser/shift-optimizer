from datetime import time

from src.domain.models import Tour, Weekday
from src.services.forecast_solver_v4 import audit_coverage, ensure_singletons_for_all_tours


def test_coverage_audit_auto_heal_singletons():
    tours = [
        Tour(id="T1", day=Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0)),
        Tour(id="T2", day=Weekday.MONDAY, start_time=time(13, 0), end_time=time(17, 0)),
    ]
    blocks = []

    audit = audit_coverage(tours, blocks)
    assert audit["tours_with_zero_candidates"] == 2

    healed_blocks, injected = ensure_singletons_for_all_tours(tours, blocks)
    assert len(injected) == 2

    audit_after = audit_coverage(tours, healed_blocks)
    assert audit_after["tours_with_zero_candidates"] == 0
    assert audit_after["min_candidates_per_tour"] >= 1
