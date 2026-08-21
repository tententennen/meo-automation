"""Grade-computing helpers for meo-score.

Internal module — all names are re-exported by score.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

_STAR_VALUES: dict[str, int] = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}

_GRADE_ORDER = ["S", "A", "B", "C", "D"]
_UNHEALTHY_THRESHOLD = "B"

_GRADE_LABEL: dict[str, str] = {
    "S": "S  ✨",
    "A": "A  ✓",
    "B": "B  〜",
    "C": "C  ⚠",
    "D": "D  ✗",
}


# ---------------------------------------------------------------------------
# Grade helpers
# ---------------------------------------------------------------------------

def _grade_rank(grade: str) -> int:
    """Return an integer rank for grade (0=S best, 4=D worst); unknown → 4."""
    try:
        return _GRADE_ORDER.index(grade)
    except ValueError:
        return 4


def _worst_grade(grades: list[str]) -> str:
    """Return the single worst (highest-rank) grade from the list."""
    if not grades:
        return "D"
    return max(grades, key=_grade_rank)


def _is_healthy(grade: str) -> bool:
    """Return True when grade is B or better (S, A, or B)."""
    return _grade_rank(grade) <= _grade_rank(_UNHEALTHY_THRESHOLD)


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def _posting_rate_grade(posts_7d: int) -> str:
    """Grade posting rate over the last 7 complete days (daily target = 7/7)."""
    if posts_7d >= 7:
        return "S"
    if posts_7d == 6:
        return "A"
    if posts_7d == 5:
        return "B"
    if posts_7d >= 3:
        return "C"
    return "D"


def _held_grade(held_count: int) -> str:
    """Grade held-review count (lower is better; 0 held = perfect)."""
    if held_count == 0:
        return "S"
    if held_count == 1:
        return "A"
    if held_count == 2:
        return "B"
    if held_count <= 4:
        return "C"
    return "D"


def _star_grade(avg_stars: float | None) -> str:
    """Grade average star rating over last 30 days (None = no data = D)."""
    if avg_stars is None:
        return "D"
    if avg_stars >= 4.8:
        return "S"
    if avg_stars >= 4.5:
        return "A"
    if avg_stars >= 4.0:
        return "B"
    if avg_stars >= 3.5:
        return "C"
    return "D"


def _drive_grade(folder_id: str) -> str:
    """Grade Drive folder configuration (configured = S; TODO placeholder = D)."""
    if not folder_id or "TODO" in folder_id:
        return "D"
    return "S"


# ---------------------------------------------------------------------------
# Metric extraction helpers
# ---------------------------------------------------------------------------

def _posts_last_7_days(post_history: list[dict[str, Any]], today: date) -> int:
    """Count posts in the last 7 complete days (yesterday back 7 days; today excluded)."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=6)
    count = 0
    for entry in post_history:
        raw = entry.get("date", "")
        try:
            d = date.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            count += 1
    return count


def _avg_stars_30_days(reply_history: list[dict[str, Any]], today: date) -> float | None:
    """Compute average star rating from replies in the last 30 complete days.

    Entries with unknown/empty star values are excluded from the average.
    Returns None when no valid star values exist in the window.
    """
    end = today - timedelta(days=1)
    start = end - timedelta(days=29)
    values: list[int] = []
    for entry in reply_history:
        raw = entry.get("date", "")
        try:
            d = date.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            val = _STAR_VALUES.get(entry.get("stars", ""), 0)
            if val > 0:
                values.append(val)
    if not values:
        return None
    return round(sum(values) / len(values), 1)
