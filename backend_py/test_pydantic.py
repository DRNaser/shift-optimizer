#!/usr/bin/env python
"""Test Pydantic model serialization."""
import pydantic
print(f"Pydantic version: {pydantic.__version__}")

from src.api.models import ScheduleResponse, BlockOutputFE, ValidationOutputFE, StatsOutputFE

# Test BlockOutputFE with pause_zone
block = BlockOutputFE(
    id="B1-T1",
    day="Mon",
    block_type="single",
    tours=[],
    total_work_hours=4.0,
    span_hours=4.0,
    pause_zone="REGULAR"
)
print(f"\nBlockOutputFE model_dump keys: {list(block.model_dump().keys())}")
print(f"pause_zone in dump: {block.model_dump().get('pause_zone')!r}")

# Test ScheduleResponse with schema_version
validation = ValidationOutputFE(is_valid=True, hard_violations=[], warnings=[])
stats = StatsOutputFE(
    total_drivers=0, total_tours_input=0, total_tours_assigned=0,
    block_counts={}, assignment_rate=0, average_driver_utilization=0,
    average_work_hours=0
)
response = ScheduleResponse(
    id="test",
    week_start="2024-01-01",
    assignments=[],
    validation=validation,
    stats=stats,
    solver_type="portfolio",
    schema_version="2.0"
)
print(f"\nScheduleResponse model_dump keys: {list(response.model_dump().keys())}")
print(f"schema_version in dump: {response.model_dump().get('schema_version')!r}")
