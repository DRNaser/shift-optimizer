# Services module - Business logic implementations
#
# SOLVER HIERARCHY:
# =================
# CANONICAL: forecast_weekly_solver.solve_forecast_weekly()
#   - For forecast-based weekly planning (the main product)
#   - Uses weekly_block_builder for blocks
#   - 4-phase optimization with FTE/PT drivers
#
# EXPERIMENTAL: forecast_solver_v4.solve_forecast_v4()
#   - Use_block/set-partitioning model
#   - Uses smart_block_builder for blocks
#   - Good for block selection experiments
#
# LEGACY: cpsat_solver.create_cpsat_schedule()
#   - Full driver-assignment model
#   - For future use when real drivers/skills/availability needed

from src.services.portfolio_controller import solve_forecast_portfolio
