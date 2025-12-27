
import re
from pathlib import Path

GERMAN_DAYS = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}
DAY_ALIASES = {
    "mo": 0, "mon": 0,
    "di": 1, "tue": 1,
    "mi": 2, "wed": 2,
    "do": 3, "thu": 3,
    "fr": 4, "fri": 4,
    "sa": 5, "sat": 5,
    "so": 6, "sun": 6,
}

def _to_minutes(hhmm):
    hhmm = hhmm.strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm)
    if not m:
        raise ValueError(f"Invalid time '{hhmm}'")
    h = int(m.group(1))
    mi = int(m.group(2))
    return h * 60 + mi

def _parse_time_range(token):
    token = token.strip()
    m = re.fullmatch(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", token)
    if not m:
        raise ValueError(f"Invalid time-range '{token}'")
    a = _to_minutes(m.group(1))
    b = _to_minutes(m.group(2))
    if b <= a:
        b += 24 * 60
    return a, b

def parse(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines()]
    cur_day = None
    tours = []
    
    for ln in lines:
        if not ln or ln == "..." or ln.startswith("#"):
            continue

        header = ln.replace("\t", " ").strip()
        low = header.lower()

        detected_day = None
        for day_name, day_idx in GERMAN_DAYS.items():
            if re.search(rf"\b{re.escape(day_name)}\b", low):
                detected_day = day_idx
                break
        if detected_day is None:
            parts = re.split(r"\s+", low)
            if parts:
                p0 = parts[0]
                if p0 in DAY_ALIASES:
                    detected_day = DAY_ALIASES[p0]
        
        if detected_day is not None:
            cur_day = detected_day
            if re.search(r"(anzahl|count)\b", low) or low in GERMAN_DAYS:
                continue

        if "-" not in ln:
            continue
        
        cols = ln.strip().split()
        if len(cols) < 2:
            print(f"Skipping cols < 2: {cols}")
            continue

        time_token = cols[0]
        count_token = cols[1]

        if not re.fullmatch(r"\d+", count_token):
             if re.fullmatch(r"\d+", cols[-1]):
                 count_token = cols[-1]
                 time_token = cols[0]
             else:
                 print(f"Skipping invalid count: {count_token}")
                 continue

        try:
             _ = _parse_time_range(time_token)
        except ValueError as e:
             print(f"Skipping value error: {e}")
             continue
        
        if cur_day is None:
            cur_day = 0
            
        count = int(count_token)
        tours.append(count)
        
    return tours

p = Path("forecast-test.txt")
print(f"File exists: {p.exists()}")
t = parse(p)
print(f"Parsed {len(t)} entries")
print(f"Total tours: {sum(t)}")
