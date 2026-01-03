import sys
import os
import time
from datetime import date, time as datetime_time

# Add project root to path
sys.path.append(os.getcwd())

from src.api.run_manager import run_manager
from src.domain.models import Tour, Driver, Weekday
from src.services.forecast_solver_v4 import ConfigV4

def main():
    print("Verifying V2 Migration via RunManager...")
    
    # 1. Create Dummy Data
    tours = [
        Tour(id="T1", day=Weekday.MONDAY, start_time=datetime_time(8,0), end_time=datetime_time(12,0)),
        Tour(id="T2", day=Weekday.MONDAY, start_time=datetime_time(13,0), end_time=datetime_time(17,0)),
    ]
    drivers = [
        Driver(id="D1", name="Test Driver")
    ]
    config = ConfigV4(target_ftes=1)
    
    # 2. Start Run
    run_id = run_manager.create_run(
        tours=tours, 
        drivers=drivers, 
        config=config, 
        week_start=date(2024, 1, 1), 
        time_budget=15.0
    )
    print(f"Run started: {run_id}")
    
    # 3. Poll
    adapter_found = False
    for i in range(20):
        ctx = run_manager.get_run(run_id)
        if i % 2 == 0:
            print(f"[{i}s] Status: {ctx.status}")
        
        # Check logs for Adapter V2 signature
        if not adapter_found:
            logs = [e for e in ctx.events if e.get("event") == "solver_log"]
            for log in logs:
                msg = log.get("payload", {}).get("msg", "")
                if "ADAPTER V2" in msg:
                     print("SUCCESS: Adapter V2 signature found in logs!")
                     adapter_found = True
        
        if ctx.status in ["COMPLETED", "FAILED", "CANCELLED"]:
            break
        time.sleep(1)
        
    # 4. Final check
    ctx = run_manager.get_run(run_id)
    if ctx.status == "COMPLETED":
        print("Run COMPLETED.")
        if ctx.result and ctx.result.solution:
            print(f"Drivers: {ctx.result.solution.kpi.get('drivers_total')}")
            print(f"Result Status: {ctx.result.solution.status}")
        else:
            print("ERROR: No result solution")
    else:
        print(f"Run FAILED: {ctx.error}")
        # Print logs for debut
        print("\n--- ERROR LOGS ---")
        logs = [e for e in ctx.events if e.get("event") in ["solver_log", "error"]]
        for log in logs:
            print(log.get("payload", {}).get("msg", str(log)))

if __name__ == "__main__":
    main()
