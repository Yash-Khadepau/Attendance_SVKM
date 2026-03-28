"""Aggregate structured attendance rows per course."""

from __future__ import annotations

import math


def aggregate_attendance(rows: list[dict]) -> dict:
    """
    Group rows by course. Only P and A count toward ``total``; NU rows are skipped.

    ``attendance_percent`` = present / total * 100 (2 decimal places); 0.0 if total is 0.
    """
    buckets: dict[str, dict[str, int]] = {}

    for row in rows:
        course = row.get("course")
        status = row.get("status")
        if not isinstance(course, str) or not course.strip():
            continue
        if isinstance(status, str):
            status = status.upper()
        if status == "NU":
            continue
        if status not in ("P", "A"):
            continue

        key = " ".join(course.split())
        if key not in buckets:
            buckets[key] = {"present": 0, "total": 0}
        buckets[key]["total"] += 1
        if status == "P":
            buckets[key]["present"] += 1

    out: dict[str, dict] = {}
    for name, counts in buckets.items():
        total = counts["total"]
        present = counts["present"]
        if total > 0:
            pct = present / total * 100.0
        else:
            pct = 0.0
        out[name] = {
            "present": present,
            "total": total,
            "attendance_percent": round(pct, 2),
        }

    return out


def compute_bunk_buffer(subject_stats: dict, target_percent: float = 75) -> dict:
    """
    Copy each subject's stats and add ``can_bunk`` / ``must_attend`` so attendance
    can stay at or above ``target_percent`` (e.g. 75 means 75%).
    """
    target = target_percent / 100.0
    result: dict[str, dict] = {}

    for name, stats in subject_stats.items():
        d = dict(stats)
        p = int(d.get("present", 0))
        t = int(d.get("total", 0))

        if t <= 0 or target <= 0:
            d["can_bunk"] = 0
            d["must_attend"] = 0
            result[name] = d
            continue

        current_percent = p / t
        if current_percent >= target:
            can_bunk = math.floor((p / target) - t)
            must_attend = 0
        else:
            can_bunk = 0
            denom = 1.0 - target
            if denom <= 0:
                must_attend = max(0, t - p)
            else:
                must_attend = math.ceil(((target * t) - p) / denom)

        d["can_bunk"] = max(0, can_bunk)
        d["must_attend"] = max(0, must_attend)
        result[name] = d

    return result
