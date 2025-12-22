"""Tests for API schemas and validation behavior."""

import pytest
from pydantic import ValidationError

from src.api.schemas import ScheduleRequest
from src.domain.models import Weekday


def _base_schedule_payload() -> dict:
    return {
        "tours": [
            {
                "id": "T1",
                "day": Weekday.MONDAY,
                "start_time": "08:00",
                "end_time": "10:00",
            }
        ],
        "drivers": [
            {
                "id": "D1",
                "name": "Driver One",
                "available_days": list(Weekday),
            }
        ],
        "week_start": "2024-01-01",
    }


def test_solver_type_normalizes_and_allows_known_values():
    payload = _base_schedule_payload()
    payload["solver_type"] = "CPSAT+LNS"

    request = ScheduleRequest(**payload)

    assert request.solver_type == "cpsat+lns"


def test_solver_type_rejects_unknown_values():
    payload = _base_schedule_payload()
    payload["solver_type"] = "anneal"

    with pytest.raises(ValidationError):
        ScheduleRequest(**payload)
