
import sys
import os
sys.path.append(os.path.join(os.getcwd(), "src"))

from src.services.portfolio_controller import run_portfolio
from src.api.forecast_router import _convert_tours
from src.api.schemas import TourInputFE
from src.services.forecast_solver_v4 import ConfigV4

def reproduce():
    tours_fe = [
        TourInputFE(id="T001", day="MON", start_time="06:00", end_time="08:30"),
        TourInputFE(id="T002", day="MON", start_time="09:00", end_time="11:30"),
        TourInputFE(id="T003", day="MON", start_time="14:00", end_time="16:30"),
    ]
    
    tours = _convert_tours(tours_fe)
    config = ConfigV4(output_profile="BEST_BALANCED")
    
    print(f"Running portfolio with {len(tours)} tours...")
    try:
        result = run_portfolio(tours, time_budget=30.0, config=config)
        print(f"Status: {result.solution.status}")
        print(f"KPI: {result.solution.kpi}")
    except Exception as e:
        print(f"Crashed with: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reproduce()
