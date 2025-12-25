from __future__ import annotations

from typing import Any, Tuple


_PAUSE_ZONE_CANON = {
    "REGULAR": "REGULAR",
    "REG": "REGULAR",
    "R": "REGULAR",
    "Z1": "REGULAR",
    "1": "REGULAR",
    "SPLIT": "SPLIT",
    "S": "SPLIT",
    "Z2": "SPLIT",
    "2": "SPLIT",
}

_PAUSE_ZONE_RANK = {
    "REGULAR": 1,
    "SPLIT": 2,
    "NONE": 99,
}


def normalize_pause_zone(value: Any) -> Tuple[str, int]:
    """
    Normalize pause_zone values to canonical keys with deterministic ranks.

    - Unknown/None/empty values -> ("NONE", 99)
    - Known variants map to REGULAR/SPLIT
    """
    if value is None:
        return ("NONE", _PAUSE_ZONE_RANK["NONE"])

    if hasattr(value, "value"):
        value = value.value

    key = str(value).strip().upper()
    if not key:
        return ("NONE", _PAUSE_ZONE_RANK["NONE"])

    canonical = _PAUSE_ZONE_CANON.get(key, "NONE")
    return (canonical, _PAUSE_ZONE_RANK.get(canonical, 99))
