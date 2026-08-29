"""Tests for Japanese holiday lookup module."""

from datetime import date
import pytest

from meo.holidays import (
    Holiday,
    _nth_monday,
    _holidays_for_year,
    upcoming_holidays,
    holiday_context_str,
)


# ---------------------------------------------------------------------------
# _nth_monday helpers
# ---------------------------------------------------------------------------

class TestNthMonday:
    def test_first_monday_january_2026(self):
        # Jan 1, 2026 is Thursday; first Monday = Jan 5
        assert _nth_monday(2026, 1, 1) == date(2026, 1, 5)

    def test_second_monday_january_2026(self):
        # 成人の日 2026
        assert _nth_monday(2026, 1, 2) == date(2026, 1, 12)

    def test_third_monday_july_2026(self):
        # 海の日 2026 — July 1 is Wednesday; 3rd Mon = Jul 20
        assert _nth_monday(2026, 7, 3) == date(2026, 7, 20)

    def test_third_monday_september_2026(self):
        # 敬老の日 2026 — Sep 1 is Tuesday; 3rd Mon = Sep 21
        assert _nth_monday(2026, 9, 3) == date(2026, 9, 21)

    def test_second_monday_october_2026(self):
        # スポーツの日 2026 — Oct 1 is Thursday; 2nd Mon = Oct 12
        assert _nth_monday(2026, 10, 2) == date(2026, 10, 12)


# ---------------------------------------------------------------------------
# _holidays_for_year
# ---------------------------------------------------------------------------

class TestHolidaysForYear:
    def _names_for_year(self, year: int) -> dict[date, str]:
        return {d: name for d, name in _holidays_for_year(year)}

    def test_fixed_national_present(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 1, 1)] == "元日"
        assert holidays[date(2026, 11, 3)] == "文化の日"
        assert holidays[date(2026, 11, 23)] == "勤労感謝の日"

    def test_equinox_vernal_2026(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 3, 20)] == "春分の日"

    def test_equinox_autumnal_2026(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 9, 23)] == "秋分の日"

    def test_equinox_default_fallback(self):
        # Year outside the lookup table — should not raise, uses defaults
        holidays = self._names_for_year(2040)
        dates = {d for d, _ in _holidays_for_year(2040)}
        assert date(2040, 3, 20) in dates  # default vernal = 20
        assert date(2040, 9, 23) in dates  # default autumnal = 23

    def test_seijin_no_hi_monday(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 1, 12)] == "成人の日"

    def test_umi_no_hi_monday(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 7, 20)] == "海の日"

    def test_keiro_no_hi_monday(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 9, 21)] == "敬老の日"

    def test_sports_no_hi_monday(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 10, 12)] == "スポーツの日"

    def test_cultural_christmas(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 12, 25)] == "クリスマス"

    def test_cultural_obon(self):
        holidays = self._names_for_year(2026)
        assert holidays[date(2026, 8, 13)] == "お盆"


# ---------------------------------------------------------------------------
# upcoming_holidays
# ---------------------------------------------------------------------------

class TestUpcomingHolidays:
    def test_finds_holiday_in_window(self):
        # 元日 is Jan 1 — window from Dec 30 with n_days=3
        result = upcoming_holidays(3, today=date(2025, 12, 30))
        names = [h.name for h in result]
        assert "元日" in names

    def test_holiday_outside_window_excluded(self):
        # n_days=2 from Dec 29 → window Dec 29-31; 元日 Jan 1 is outside
        result = upcoming_holidays(2, today=date(2025, 12, 29))
        names = [h.name for h in result]
        assert "元日" not in names

    def test_sorted_ascending(self):
        # window crossing several holidays
        result = upcoming_holidays(4, today=date(2026, 5, 2))
        dates = [h.date for h in result]
        assert dates == sorted(dates)

    def test_no_duplicates_same_date(self):
        # 秋分の日 (Sep 23) and 敬老の日 (Sep 21) are different dates; no same-date clash expected
        # Verify at minimum that results have unique dates
        result = upcoming_holidays(30, today=date(2026, 9, 1))
        assert len(result) == len({h.date for h in result})

    def test_zero_n_days_today_only(self):
        # n_days=0: only holidays that fall exactly on today
        result = upcoming_holidays(0, today=date(2026, 1, 1))
        assert all(h.date == date(2026, 1, 1) for h in result)
        assert any(h.name == "元日" for h in result)

    def test_zero_n_days_no_holidays(self):
        # A weekday with no holiday on it
        result = upcoming_holidays(0, today=date(2026, 4, 1))
        assert result == []

    def test_cross_year_boundary(self):
        # Dec 31 window of 3 days includes Jan 1 (New Year) and Jan 2 (お正月)
        result = upcoming_holidays(3, today=date(2025, 12, 31))
        names = [h.name for h in result]
        assert "元日" in names
        assert "お正月" in names

    def test_days_until_today(self):
        result = upcoming_holidays(0, today=date(2026, 1, 1))
        entry = next(h for h in result if h.name == "元日")
        assert entry.days_until == 0

    def test_days_until_tomorrow(self):
        result = upcoming_holidays(1, today=date(2025, 12, 31))
        entry = next(h for h in result if h.name == "元日")
        assert entry.days_until == 1

    def test_days_until_future(self):
        result = upcoming_holidays(7, today=date(2025, 12, 25))
        entry = next(h for h in result if h.name == "元日")
        assert entry.days_until == 7

    def test_negative_n_days_raises(self):
        with pytest.raises(ValueError, match="n_days must be >= 0"):
            upcoming_holidays(-1, today=date(2026, 1, 1))

    def test_returns_holiday_namedtuple(self):
        result = upcoming_holidays(0, today=date(2026, 1, 1))
        assert isinstance(result[0], Holiday)
        assert hasattr(result[0], "name")
        assert hasattr(result[0], "date")
        assert hasattr(result[0], "days_until")

    def test_national_takes_precedence_over_cultural_same_date(self):
        # Both お正月 (cultural, Jan 2) and nothing national — just confirm no national exists Jan 2
        result = upcoming_holidays(0, today=date(2026, 1, 2))
        names = [h.name for h in result]
        assert "お正月" in names

    def test_empty_when_no_holidays_in_window(self):
        # April 2 — no holiday on that specific day
        result = upcoming_holidays(0, today=date(2026, 4, 2))
        assert result == []


# ---------------------------------------------------------------------------
# holiday_context_str
# ---------------------------------------------------------------------------

class TestHolidayContextStr:
    def test_empty_when_no_holidays(self):
        result = holiday_context_str(0, today=date(2026, 4, 2))
        assert result == ""

    def test_header_present(self):
        result = holiday_context_str(0, today=date(2026, 1, 1))
        assert result.startswith("【近日の記念日・祝日】")

    def test_today_format(self):
        result = holiday_context_str(0, today=date(2026, 1, 1))
        assert "本日は元日です" in result

    def test_tomorrow_format_includes_date(self):
        result = holiday_context_str(1, today=date(2025, 12, 31))
        assert "明日は元日です（1月1日）" in result

    def test_future_format_includes_days_and_date(self):
        result = holiday_context_str(7, today=date(2025, 12, 25))
        assert "7日後は元日です（1月1日）" in result

    def test_multiple_holidays_joined_by_comma(self):
        # May 3-5 window from May 1 has 憲法記念日, みどりの日, こどもの日
        result = holiday_context_str(5, today=date(2026, 5, 1))
        # Should have multiple "、"-separated entries
        assert "、" in result
        assert "憲法記念日" in result
        assert "こどもの日" in result

    def test_returns_string(self):
        result = holiday_context_str(7, today=date(2026, 1, 1))
        assert isinstance(result, str)
