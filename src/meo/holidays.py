"""Japanese national holiday and cultural event lookup.

Provides upcoming_holidays() and holiday_context_str() for injecting
holiday-awareness into LLM content prompts.  No external API is needed —
holidays are computed from statutory rules and per-year lookup tables for
moveable dates (equinoxes).

Sources:
  国民の祝日に関する法律（Act on National Holidays）
  https://elaws.e-gov.go.jp/document?lawid=323AC0000000178
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple


class Holiday(NamedTuple):
    name: str        # Japanese name (e.g. "元日")
    date: date       # calendar date
    days_until: int  # 0 = today, 1 = tomorrow, …


# Fixed-date national holidays (month, day, name).
# Equinoxes and Monday holidays are computed separately below.
_FIXED_NATIONAL: list[tuple[int, int, str]] = [
    (1, 1, "元日"),
    (2, 11, "建国記念の日"),
    (2, 23, "天皇誕生日"),
    (4, 29, "昭和の日"),
    (5, 3, "憲法記念日"),
    (5, 4, "みどりの日"),
    (5, 5, "こどもの日"),
    (8, 11, "山の日"),
    (11, 3, "文化の日"),
    (11, 23, "勤労感謝の日"),
]

# Culturally significant dates that are not legal holidays but are widely
# observed in Japan and relevant to beauty/fitness promotions.
_FIXED_CULTURAL: list[tuple[int, int, str]] = [
    (1, 2, "お正月"),
    (1, 3, "お正月"),
    (2, 14, "バレンタインデー"),
    (3, 14, "ホワイトデー"),
    (7, 7, "七夕"),
    (8, 13, "お盆"),
    (8, 14, "お盆"),
    (8, 15, "お盆"),
    (12, 24, "クリスマスイブ"),
    (12, 25, "クリスマス"),
    (12, 31, "大晦日"),
]

# Vernal equinox (春分の日) day-of-month in March, per year.
# Source: Japanese National Observatory announcements.
_VERNAL_EQUINOX_DAY: dict[int, int] = {
    2024: 20, 2025: 20, 2026: 20, 2027: 21,
    2028: 20, 2029: 20, 2030: 20,
}

# Autumnal equinox (秋分の日) day-of-month in September, per year.
_AUTUMNAL_EQUINOX_DAY: dict[int, int] = {
    2024: 22, 2025: 23, 2026: 23, 2027: 23,
    2028: 22, 2029: 23, 2030: 23,
}

_VERNAL_EQUINOX_DEFAULT = 20
_AUTUMNAL_EQUINOX_DEFAULT = 23


def _nth_monday(year: int, month: int, n: int) -> date:
    """Return the n-th Monday (1-based) in year/month."""
    first = date(year, month, 1)
    offset = (0 - first.weekday()) % 7  # days until the first Monday
    return first + timedelta(days=offset + (n - 1) * 7)


def _holidays_for_year(year: int) -> list[tuple[date, str]]:
    """Return (date, name) pairs for all holidays in the given calendar year.

    National holidays are listed before cultural ones so that when two events
    fall on the same date, the national holiday takes precedence in deduplication.
    """
    result: list[tuple[date, str]] = []

    for month, day, name in _FIXED_NATIONAL + _FIXED_CULTURAL:
        try:
            result.append((date(year, month, day), name))
        except ValueError:  # pragma: no cover — guard for bad static data
            pass

    # Monday holidays (ハッピーマンデー制度)
    result.append((_nth_monday(year, 1, 2), "成人の日"))     # 2nd Monday, January
    result.append((_nth_monday(year, 7, 3), "海の日"))       # 3rd Monday, July
    result.append((_nth_monday(year, 9, 3), "敬老の日"))     # 3rd Monday, September
    result.append((_nth_monday(year, 10, 2), "スポーツの日"))  # 2nd Monday, October

    # Equinoxes
    vernal_day = _VERNAL_EQUINOX_DAY.get(year, _VERNAL_EQUINOX_DEFAULT)
    result.append((date(year, 3, vernal_day), "春分の日"))
    autumnal_day = _AUTUMNAL_EQUINOX_DAY.get(year, _AUTUMNAL_EQUINOX_DEFAULT)
    result.append((date(year, 9, autumnal_day), "秋分の日"))

    return result


def upcoming_holidays(n_days: int = 7, *, today: date | None = None) -> list[Holiday]:
    """Return holidays occurring within [today, today + n_days] inclusive.

    When multiple holidays share a date, only the first encountered (national
    before cultural) is kept to avoid duplicates.  Results are sorted ascending
    by date.

    Args:
        n_days: Look-ahead window in days.  0 = today only.  Must be >= 0.
        today:  Override "today" for testing (uses date.today() when None).

    Raises:
        ValueError: If n_days < 0.
    """
    if today is None:
        today = date.today()
    if n_days < 0:
        raise ValueError(f"n_days must be >= 0, got {n_days}")
    end = today + timedelta(days=n_days)

    seen: dict[date, str] = {}
    for year in sorted({today.year, end.year}):
        for d, name in _holidays_for_year(year):
            if today <= d <= end and d not in seen:
                seen[d] = name

    return [
        Holiday(name=name, date=d, days_until=(d - today).days)
        for d, name in sorted(seen.items())
    ]


def holiday_context_str(n_days: int = 7, *, today: date | None = None) -> str:
    """Return a prompt-ready string listing upcoming holidays, or '' if none.

    Callers can safely use the return value as a falsy check: an empty string
    means no holidays are in the window and the line should be omitted from the
    LLM prompt.

    Example output:
        "【近日の記念日・祝日】3日後は山の日です（8月11日）、本日はお盆です"
    """
    holidays = upcoming_holidays(n_days, today=today)
    if not holidays:
        return ""
    parts: list[str] = []
    for h in holidays:
        if h.days_until == 0:
            parts.append(f"本日は{h.name}です")
        elif h.days_until == 1:
            parts.append(f"明日は{h.name}です（{h.date.month}月{h.date.day}日）")
        else:
            parts.append(f"{h.days_until}日後は{h.name}です（{h.date.month}月{h.date.day}日）")
    return "【近日の記念日・祝日】" + "、".join(parts)
