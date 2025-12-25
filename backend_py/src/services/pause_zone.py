from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

PAUSE_ZONE_RANK = {
    "Z0": 0,
    "Z1": 1,
    "Z2": 2,
    "Z3": 3,
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "A": 0,
    "B": 1,
    "C": 2,
    "D": 3,
    "REGULAR": 1,
    "SPLIT": 2,
    "NONE": 99,
    "": 99,
}


def normalize_pause_zone(zone: object) -> str:
    if zone is None:
        return "NONE"
    text = str(zone).strip().upper()
    if not text:
        return "NONE"
    if text in {"REGULAR", "SPLIT"}:
        return text
    match = re.search(r"(\d+)", text)
    if text.startswith("Z") and match:
        return f"Z{int(match.group(1))}"
    if match and len(match.group(1)) <= 2:
        return str(int(match.group(1)))
    return text


def pause_zone_rank(zone: object) -> int:
    normalized = normalize_pause_zone(zone)
    return PAUSE_ZONE_RANK.get(normalized, 99)


def pause_zone_distribution(zones: Iterable[object]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for zone in zones:
        counter[normalize_pause_zone(zone)] += 1
    return counter
