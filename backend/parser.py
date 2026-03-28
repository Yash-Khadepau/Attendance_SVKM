import re
from calendar import monthrange
from datetime import date

from backend.aggregate import aggregate_attendance, compute_bunk_buffer

# Row starts with serial number, then course text up to T1:/P1:/U1: style block
_CODE_START = re.compile(r"(?i)(?=(?:[tpu])\d+:)")

# Prefix after course: T1:B Tech CE:B, P1:B Tech CE:B2, etc.
_TECH_CODE_PREFIX = re.compile(
    r"^(?:[TPU])\d+:\s*B\s+Tech\s+[A-Za-z0-9]+\s*:\s*[A-Za-z0-9]+\s*",
    re.IGNORECASE,
)

# Tail: "Jan 7, 2026 10:00:01 AM 11:00:00 AM P"
_ATTENDANCE_TAIL = re.compile(
    r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s+"
    r"(\d{1,2}:\d{2}:\d{2})\s*(AM|PM)\s+"
    r"(\d{1,2}:\d{2}:\d{2})\s*(AM|PM)\s+"
    r"(P|A|NU)\s*$",
    re.IGNORECASE,
)

_HEADER_LINE = re.compile(
    r"^\s*(Sr\.?|S\.?\s*No\.?|Course\s*Name|Subject|Date|Start|End|Time|Status|Attendance|Remark)\b",
    re.IGNORECASE,
)

# Lines containing any of these (case-insensitive) are not attendance rows.
_STRUCTURE_SKIP_SUBSTRINGS = (
    "page",
    "attendance report",
    "student name",
    "p - present",
    "ps:",
    "sr attenda",
)

_MONTH_ALIASES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.lower().startswith("page"):
        return True
    if _HEADER_LINE.match(s):
        return True
    return False


def _clean_course(name: str) -> str:
    s = " ".join(name.split())
    s = _TECH_CODE_PREFIX.sub("", s)
    while True:
        nxt = _TECH_CODE_PREFIX.sub("", s)
        if nxt == s:
            break
        s = nxt
    s = " ".join(s.split())
    return s.strip()


def _parse_month_day_year(month_str: str, day_str: str, year_str: str) -> str | None:
    key = month_str.lower().strip()
    month = _MONTH_ALIASES.get(key)
    if month is None:
        return None
    try:
        y = int(year_str)
        d = int(day_str)
    except ValueError:
        return None
    if d < 1 or d > monthrange(y, month)[1]:
        return None
    return date(y, month, d).isoformat()


def _strip_leading_tech_codes(s: str) -> str:
    rest = s.strip()
    while True:
        nxt = _TECH_CODE_PREFIX.sub("", rest)
        if nxt == rest:
            break
        rest = nxt.strip()
    return rest


def _structure_line_irrelevant(line: str) -> bool:
    low = line.lower()
    return any(token in low for token in _STRUCTURE_SKIP_SUBSTRINGS)


def _ends_with_attendance_status(line: str) -> bool:
    return bool(re.search(r"\s(P|A|NU)\s*$", line.strip(), re.IGNORECASE))


def _format_hms_ampm(clock: str, ampm: str) -> str:
    parts = clock.split(":")
    if len(parts) != 3:
        return f"{clock.strip()} {ampm.strip().upper()}".strip()
    h, mi, sec = parts
    return f"{int(h)}:{mi}:{sec} {ampm.strip().upper()}"


def structure_rows(lines: list[str]) -> list[dict]:
    """
    Convert raw PDF text lines into structured rows with course, ISO date,
    clock times, and status.

    Skips lines that mention headers/legends (Page, Attendance Report, etc.).
    Valid rows start with a serial number and end with P, A, or NU.
    """
    rows: list[dict] = []

    for line in lines:
        s = " ".join(line.split())
        if not s:
            continue
        if _structure_line_irrelevant(s):
            continue
        if not re.match(r"^\d+\s+", s):
            continue
        if not _ends_with_attendance_status(s):
            continue

        m_head = re.match(r"^(\d+)\s+(.+)$", s)
        if not m_head:
            continue

        rest_after_serial = m_head.group(2).strip()
        parts = _CODE_START.split(rest_after_serial, maxsplit=1)
        if len(parts) < 2:
            continue

        course_raw, suffix_with_codes = parts[0], parts[1]
        course = _clean_course(course_raw)
        if not course:
            continue

        remainder = _strip_leading_tech_codes(suffix_with_codes)
        tail = _ATTENDANCE_TAIL.match(remainder)
        if not tail:
            continue

        month_name, day_s, year_s = tail.group(1), tail.group(2), tail.group(3)
        iso_date = _parse_month_day_year(month_name, day_s, year_s)
        if not iso_date:
            continue

        status = tail.group(8).upper()
        if status not in ("P", "A", "NU"):
            continue

        start_time = _format_hms_ampm(tail.group(4), tail.group(5))
        end_time = _format_hms_ampm(tail.group(6), tail.group(7))

        rows.append(
            {
                "course": course,
                "date": iso_date,
                "start_time": start_time,
                "end_time": end_time,
                "status": status,
            }
        )

    return rows


def parse_attendance_lines(lines: list[str]) -> list[dict]:
    """
    Convert PDF text lines into attendance rows.

    Pattern:
    [number] [course][T1|P1|U1:...] [Month Day, Year] [start] [end] [P/A/NU]
    """
    rows: list[dict] = []

    for line in lines:
        if _is_noise_line(line):
            continue

        s = line.strip()
        m_head = re.match(r"^(\d+)\s+(.+)$", s)
        if not m_head:
            continue

        rest_after_serial = m_head.group(2)
        parts = _CODE_START.split(rest_after_serial, maxsplit=1)
        if len(parts) < 2:
            continue

        course_raw, suffix_with_codes = parts[0], parts[1]
        course = _clean_course(course_raw)
        if not course:
            continue

        remainder = _strip_leading_tech_codes(suffix_with_codes)
        tail = _ATTENDANCE_TAIL.match(remainder)
        if not tail:
            continue

        month_name, day_s, year_s = tail.group(1), tail.group(2), tail.group(3)
        iso_date = _parse_month_day_year(month_name, day_s, year_s)
        if not iso_date:
            continue

        status = tail.group(8).upper()
        if status not in ("P", "A", "NU"):
            continue

        rows.append(
            {
                "course": course,
                "date": iso_date,
                "status": status,
            }
        )

    return rows
