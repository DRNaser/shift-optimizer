
import pytest
from src.domain.models import Block, Tour, Weekday
from src.services.smart_block_builder import _smart_cap_with_1er_guarantee, ScoredBlock

def test_quota_prevents_starvation():
    """
    Regression Test: Ensure that 2-tour blocks are not starved by 3-tour blocks.
    We simulate a realistic pipeline where tours exist and are protected by 1-blocks.
    """
    num_tours = 50
    tours = [
        Tour(id=f"T{i}", day=Weekday.MONDAY, start_time="08:00", end_time="12:00")
        for i in range(num_tours)
    ]
    
    scored = []
    
    # 1. ADD 1er BLOCKS (Protected Set)
    # One per tour, Score 10 (Low score, but protected)
    for t in tours:
        b = Block(id=f"B1-{t.id}", day=Weekday.MONDAY, tours=[t])
        scored.append(ScoredBlock(block=b, score=10.0))
        
    # 2. ADD 3er BLOCKS (Score 150 - High)
    # Create 400 sliding window blocks to ensure unique coverage
    # (T0,T1,T2), (T1,T2,T3)...
    for i in range(400):
        ts = [tours[(i+j)%num_tours] for j in range(3)]
        # Sort tours by id/time for consistency (Block validation requires sorted by start time)
        # Here verification uses start_time. All are 08:00.
        # But Block also requires sorted. Since times equal, sort by creation order?
        # Actually my Block validation checks `sorted(tours, key=start_time)`. 
        # Since all times equal, it's stable.
        
        b = Block(id=f"B3-{i}", day=Weekday.MONDAY, tours=ts)
        scored.append(ScoredBlock(block=b, score=150.0))
        
    # 3. ADD 2er BLOCKS (Score 100 - Lower than 3er)
    # Create 200 sliding window blocks
    for i in range(200):
        ts = [tours[(i+j)%num_tours] for j in range(2)]
        b = Block(id=f"B2-{i}", day=Weekday.MONDAY, tours=ts)
        scored.append(ScoredBlock(block=b, score=100.0))
        
    global_n = 200
    # Protected = 50. Remaining = 150.
    # Quota 30% of 150 = 45.
    
    kept, stats = _smart_cap_with_1er_guarantee(scored, tours, global_n, quota_2er=0.30)
    
    # Count NON-PROTECTED kept blocks
    # Protected are 1ers.
    kept_2er = sum(1 for b in kept if len(b.tours) == 2)
    kept_3er = sum(1 for b in kept if len(b.tours) == 3)
    
    print(f"Kept 2er: {kept_2er}, Kept 3er: {kept_3er}")
    
    # Expect ~45 2er.
    assert kept_2er >= 40, f"Expected ~45 2er, got {kept_2er}"
    assert kept_3er <= 110
    
def test_adaptive_quota_low_availability():
    """
    Ensure we don't force quota if 2er candidates are scarce.
    """
    num_tours = 50
    tours = [
        Tour(id=f"T{i}", day=Weekday.MONDAY, start_time="08:00", end_time="12:00")
        for i in range(num_tours)
    ]
    scored = []
    
    # 1. Protected 1ers
    for t in tours:
        b = Block(id=f"B1-{t.id}", day=Weekday.MONDAY, tours=[t])
        scored.append(ScoredBlock(block=b, score=10.0))
        
    # 2. Many 3ers (400)
    for i in range(400):
        ts = [tours[(i+j)%num_tours] for j in range(3)]
        b = Block(id=f"B3-{i}", day=Weekday.MONDAY, tours=ts)
        scored.append(ScoredBlock(block=b, score=150.0))
        
    # 3. FEW 2ers (Only 5)
    for i in range(5):
        ts = [tours[(i+j)%num_tours] for j in range(2)]
        b = Block(id=f"B2-{i}", day=Weekday.MONDAY, tours=ts)
        scored.append(ScoredBlock(block=b, score=100.0))
        
    global_n = 200
    # Remaining = 150.
    # 2er Availability: 5. 3er: 400. Ratio ~1.2%.
    # Floor 5% -> Target 7.5 -> 7.
    # Take MIN(7, Available 5) = 5.
    
    kept, stats = _smart_cap_with_1er_guarantee(scored, tours, global_n, quota_2er=0.30)
    
    kept_2er = sum(1 for b in kept if len(b.tours) == 2)
    
    assert kept_2er == 5, f"Expected 5 2er, got {kept_2er}"
