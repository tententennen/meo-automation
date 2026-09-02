"""Tests for meo-rating-alert."""

from __future__ import annotations

import sys
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime as _real_datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import requests

from meo.tools.rating_alert import (
    _DEFAULT_MIN_DROP,
    _DEFAULT_MIN_REPLIES,
    _DEFAULT_WINDOW_DAYS,
    _avg_stars,
    _format_alert,
    _send_alert,
    _star_value,
    _window_entries,
    main,
    run_rating_alert,
)

# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

_STORES = [
    {
        "key": "the_body_osaka_shinsaibashi",
        "name": "THE BODY 大阪 心斎橋店",
        "industry": "beauty_salon",
        "location_id": "accounts/1/locations/1",
        "drive_folder_id": "folder_abc",
    },
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "accounts/1/locations/2",
        "drive_folder_id": "folder_xyz",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "industry": "fitness_studio",
        "location_id": "accounts/1/locations/3",
        "drive_folder_id": "folder_mbk",
    },
]


def _reply(date_str: str, stars: str) -> dict:
    return {"date": date_str, "stars": stars, "review_id": f"r_{date_str}_{stars}"}


# 14-day window ending 2026-08-27 (yesterday when today=2026-08-28):
# cur_end   = 2026-08-27
# cur_start = 2026-08-14
# prev_end  = 2026-08-13
# prev_start= 2026-07-31

_TODAY = date(2026, 8, 28)

# High previous period (avg 4.5), low current (avg 2.0) → should alert
_DECLINING_HISTORY = [
    # Previous window (2026-07-31 → 2026-08-13): three 5-stars, three 4-stars
    _reply("2026-08-01", "FIVE"),
    _reply("2026-08-05", "FIVE"),
    _reply("2026-08-10", "FIVE"),
    _reply("2026-08-12", "FOUR"),
    _reply("2026-08-13", "FOUR"),
    # Current window (2026-08-14 → 2026-08-27): three 2-stars, one 1-star
    _reply("2026-08-15", "TWO"),
    _reply("2026-08-18", "TWO"),
    _reply("2026-08-22", "TWO"),
    _reply("2026-08-25", "ONE"),
]

# Stable history: both periods ~4.5 → should NOT alert
_STABLE_HISTORY = [
    _reply("2026-08-01", "FIVE"),
    _reply("2026-08-10", "FIVE"),
    _reply("2026-08-12", "FOUR"),
    _reply("2026-08-15", "FIVE"),
    _reply("2026-08-20", "FOUR"),
    _reply("2026-08-25", "FIVE"),
]

_TODAY_STR = "2026-08-28 09:00 JST"


class _FakeDatetime(_real_datetime):
    """Freeze datetime.now() to _TODAY for tests that call main() directly."""
    @classmethod
    def now(cls, tz=None):
        return _real_datetime(2026, 8, 28, 9, 0, 0, tzinfo=tz or ZoneInfo("Asia/Tokyo"))


@contextmanager
def _freeze_main_date():
    """Freeze datetime.now in rating_alert so main() uses _TODAY."""
    with patch("meo.tools.rating_alert.datetime", _FakeDatetime):
        yield


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.rating_alert.cfg.store_list", lambda: list(_STORES))


# ---------------------------------------------------------------------------
# _star_value
# ---------------------------------------------------------------------------

class TestStarValue:
    def test_known_values(self):
        assert _star_value("ONE") == 1
        assert _star_value("TWO") == 2
        assert _star_value("THREE") == 3
        assert _star_value("FOUR") == 4
        assert _star_value("FIVE") == 5

    def test_unknown_returns_zero(self):
        assert _star_value("") == 0
        assert _star_value("SIX") == 0


# ---------------------------------------------------------------------------
# _avg_stars
# ---------------------------------------------------------------------------

class TestAvgStars:
    def test_returns_none_when_empty(self):
        assert _avg_stars([]) is None

    def test_returns_none_when_no_valid_stars(self):
        assert _avg_stars([{"stars": ""}, {"stars": "UNKNOWN"}]) is None

    def test_single_entry(self):
        assert _avg_stars([{"stars": "FIVE"}]) == 5.0

    def test_mixed_entries(self):
        entries = [{"stars": "FIVE"}, {"stars": "THREE"}, {"stars": "ONE"}]
        assert _avg_stars(entries) == pytest.approx(3.0)

    def test_skips_unknown_stars(self):
        entries = [{"stars": "FIVE"}, {"stars": "UNKNOWN"}, {"stars": "THREE"}]
        result = _avg_stars(entries)
        assert result == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# _window_entries
# ---------------------------------------------------------------------------

class TestWindowEntries:
    def test_returns_entries_within_range(self):
        history = [
            _reply("2026-08-14", "FIVE"),
            _reply("2026-08-20", "THREE"),
            _reply("2026-08-27", "ONE"),
        ]
        result = _window_entries(history, date(2026, 8, 14), date(2026, 8, 27))
        assert len(result) == 3

    def test_excludes_entries_outside_range(self):
        history = [
            _reply("2026-08-13", "FIVE"),   # one day before start
            _reply("2026-08-14", "THREE"),  # start
            _reply("2026-08-27", "ONE"),    # end
            _reply("2026-08-28", "FOUR"),   # one day after end
        ]
        result = _window_entries(history, date(2026, 8, 14), date(2026, 8, 27))
        assert len(result) == 2

    def test_includes_boundary_dates(self):
        history = [_reply("2026-08-14", "FIVE"), _reply("2026-08-27", "FOUR")]
        result = _window_entries(history, date(2026, 8, 14), date(2026, 8, 27))
        assert len(result) == 2

    def test_skips_entries_with_no_date(self):
        history = [{"stars": "FIVE"}, _reply("2026-08-20", "THREE")]
        result = _window_entries(history, date(2026, 8, 14), date(2026, 8, 27))
        assert len(result) == 1

    def test_skips_entries_with_invalid_date(self):
        history = [{"date": "not-a-date", "stars": "FIVE"}, _reply("2026-08-20", "THREE")]
        result = _window_entries(history, date(2026, 8, 14), date(2026, 8, 27))
        assert len(result) == 1

    def test_returns_empty_when_no_history(self):
        assert _window_entries([], date(2026, 8, 14), date(2026, 8, 27)) == []


# ---------------------------------------------------------------------------
# run_rating_alert
# ---------------------------------------------------------------------------

class TestRunRatingAlert:
    def test_alerts_when_rating_declines(self):
        with patch(
            "meo.tools.rating_alert.get_reply_history",
            return_value=_DECLINING_HISTORY,
        ):
            alerts = run_rating_alert([_STORES[1]], today=_TODAY)
        assert len(alerts) == 1
        assert alerts[0]["store_key"] == "the_body_kyoto"
        assert alerts[0]["drop"] > 0

    def test_no_alert_when_stable(self):
        with patch(
            "meo.tools.rating_alert.get_reply_history",
            return_value=_STABLE_HISTORY,
        ):
            alerts = run_rating_alert([_STORES[0]], today=_TODAY)
        assert alerts == []

    def test_no_alert_when_current_period_empty(self):
        # Only previous period has data
        history = [
            _reply("2026-08-01", "FIVE"),
            _reply("2026-08-05", "THREE"),
        ]
        with patch("meo.tools.rating_alert.get_reply_history", return_value=history):
            alerts = run_rating_alert([_STORES[0]], today=_TODAY)
        assert alerts == []

    def test_no_alert_when_previous_period_empty(self):
        # Only current period has data
        history = [
            _reply("2026-08-15", "ONE"),
            _reply("2026-08-20", "TWO"),
            _reply("2026-08-25", "ONE"),
        ]
        with patch("meo.tools.rating_alert.get_reply_history", return_value=history):
            alerts = run_rating_alert([_STORES[0]], today=_TODAY)
        assert alerts == []

    def test_no_alert_below_min_replies(self):
        # Only 2 current replies — below default min_replies=3
        history = [
            _reply("2026-08-01", "FIVE"),
            _reply("2026-08-05", "FIVE"),
            _reply("2026-08-10", "FIVE"),
            _reply("2026-08-15", "ONE"),   # current window
            _reply("2026-08-20", "ONE"),   # current window
        ]
        with patch("meo.tools.rating_alert.get_reply_history", return_value=history):
            alerts = run_rating_alert([_STORES[0]], today=_TODAY, min_replies=3)
        assert alerts == []

    def test_alert_when_min_replies_satisfied(self):
        history = [
            _reply("2026-08-01", "FIVE"),
            _reply("2026-08-05", "FIVE"),
            _reply("2026-08-10", "FIVE"),
            _reply("2026-08-15", "ONE"),
            _reply("2026-08-20", "ONE"),
            _reply("2026-08-25", "ONE"),
        ]
        with patch("meo.tools.rating_alert.get_reply_history", return_value=history):
            alerts = run_rating_alert([_STORES[0]], today=_TODAY, min_replies=3)
        assert len(alerts) == 1

    def test_no_alert_below_min_drop(self):
        # Small drop (< 0.5) should not alert
        history = [
            _reply("2026-08-01", "FIVE"),
            _reply("2026-08-10", "FIVE"),
            _reply("2026-08-12", "FIVE"),  # prev avg=5.0
            _reply("2026-08-15", "FIVE"),
            _reply("2026-08-20", "FIVE"),
            _reply("2026-08-25", "FOUR"),  # cur avg=4.67
        ]
        with patch("meo.tools.rating_alert.get_reply_history", return_value=history):
            alerts = run_rating_alert([_STORES[0]], today=_TODAY, min_drop=0.5)
        assert alerts == []

    def test_alert_dict_fields(self):
        with patch(
            "meo.tools.rating_alert.get_reply_history",
            return_value=_DECLINING_HISTORY,
        ):
            alerts = run_rating_alert([_STORES[1]], today=_TODAY)
        assert len(alerts) == 1
        a = alerts[0]
        assert "store_key" in a
        assert "store_name" in a
        assert "cur_avg" in a
        assert "prev_avg" in a
        assert "drop" in a
        assert "cur_count" in a
        assert "prev_count" in a
        assert "cur_start" in a
        assert "cur_end" in a
        assert "prev_start" in a
        assert "prev_end" in a
        assert "cur_distribution" in a

    def test_alert_contains_correct_window_dates(self):
        with patch(
            "meo.tools.rating_alert.get_reply_history",
            return_value=_DECLINING_HISTORY,
        ):
            alerts = run_rating_alert([_STORES[1]], today=_TODAY, window_days=14)
        a = alerts[0]
        assert a["cur_end"] == "2026-08-27"    # yesterday
        assert a["cur_start"] == "2026-08-14"
        assert a["prev_end"] == "2026-08-13"
        assert a["prev_start"] == "2026-07-31"

    def test_multiple_stores_only_declining_alerted(self):
        def _history(key):
            if key == "the_body_kyoto":
                return _DECLINING_HISTORY
            return _STABLE_HISTORY

        with patch(
            "meo.tools.rating_alert.get_reply_history",
            side_effect=_history,
        ):
            alerts = run_rating_alert(_STORES, today=_TODAY)

        alerted_keys = {a["store_key"] for a in alerts}
        assert "the_body_kyoto" in alerted_keys
        assert "the_body_osaka_shinsaibashi" not in alerted_keys
        assert "mybear_studio_kyoto" not in alerted_keys

    def test_custom_window_days(self):
        # Use a 7-day window
        with patch(
            "meo.tools.rating_alert.get_reply_history",
            return_value=_DECLINING_HISTORY,
        ):
            alerts = run_rating_alert([_STORES[1]], today=_TODAY, window_days=7)
        if alerts:
            a = alerts[0]
            assert a["cur_end"] == "2026-08-27"
            assert a["cur_start"] == "2026-08-21"

    def test_empty_history_returns_no_alert(self):
        with patch("meo.tools.rating_alert.get_reply_history", return_value=[]):
            alerts = run_rating_alert(_STORES, today=_TODAY)
        assert alerts == []


# ---------------------------------------------------------------------------
# _format_alert
# ---------------------------------------------------------------------------

class TestFormatAlert:
    def _make_alert(self, drop=1.5, cur_avg=2.0, prev_avg=3.5,
                    cur_count=4, prev_count=5):
        return {
            "store_key": "the_body_kyoto",
            "store_name": "THE BODY 京都店",
            "cur_avg": cur_avg,
            "prev_avg": prev_avg,
            "drop": drop,
            "cur_count": cur_count,
            "prev_count": prev_count,
            "cur_start": "2026-08-14",
            "cur_end": "2026-08-27",
            "prev_start": "2026-07-31",
            "prev_end": "2026-08-13",
            "cur_distribution": Counter({"TWO": 3, "ONE": 1}),
        }

    def test_contains_store_name(self):
        msg = _format_alert([self._make_alert()], today_str=_TODAY_STR)
        assert "THE BODY 京都店" in msg

    def test_contains_drop_value(self):
        msg = _format_alert([self._make_alert(drop=1.5)], today_str=_TODAY_STR)
        assert "1.50" in msg

    def test_contains_avg_star_strings(self):
        msg = _format_alert([self._make_alert(cur_avg=2.0, prev_avg=3.5)], today_str=_TODAY_STR)
        assert "2.00" in msg
        assert "3.50" in msg

    def test_contains_window_dates(self):
        msg = _format_alert([self._make_alert()], today_str=_TODAY_STR)
        assert "2026-08-14" in msg
        assert "2026-08-27" in msg

    def test_header_mentions_store_count(self):
        msg = _format_alert([self._make_alert(), self._make_alert()], today_str=_TODAY_STR)
        assert "2店舗" in msg

    def test_empty_alerts_not_called_in_practice(self):
        # _format_alert is only called when alerts is non-empty, but it
        # should not raise when called with an empty list
        msg = _format_alert([], today_str=_TODAY_STR)
        assert "0店舗" in msg

    def test_distribution_lines_present(self):
        msg = _format_alert([self._make_alert()], today_str=_TODAY_STR)
        # Distribution should show star symbols for ratings with count > 0
        assert "★★☆☆☆" in msg or "TWO" in msg or "2件" in msg

    def test_window_days_in_header(self):
        msg = _format_alert([self._make_alert()], window_days=7, today_str=_TODAY_STR)
        assert "7日" in msg


# ---------------------------------------------------------------------------
# _send_alert
# ---------------------------------------------------------------------------

class TestSendAlert:
    def test_returns_false_when_no_url(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert _send_alert("test") is False

    def test_sends_post_when_url_set(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("meo.tools.rating_alert.requests.post", return_value=mock_resp) as mock_post:
            result = _send_alert("message text")
        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["text"] == "message text"

    def test_returns_false_on_http_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("meo.tools.rating_alert.requests.post", return_value=mock_resp):
            result = _send_alert("msg")
        assert result is False

    def test_returns_false_on_connection_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        with patch(
            "meo.tools.rating_alert.requests.post",
            side_effect=Exception("connection refused"),
        ):
            result = _send_alert("msg")
        assert result is False


# ---------------------------------------------------------------------------
# main() — CLI
# ---------------------------------------------------------------------------

class TestMain:
    def _run(self, argv, declining=False, monkeypatch=None):
        if monkeypatch:
            monkeypatch.setattr(sys, "argv", ["meo-rating-alert"] + argv)
        history = _DECLINING_HISTORY if declining else _STABLE_HISTORY
        with patch("meo.tools.rating_alert.get_reply_history", return_value=history):
            with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
                with pytest.raises(SystemExit) as exc:
                    main()
        return exc.value.code

    def test_exits_0_when_no_declines(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert", "--dry-run"])
        with patch("meo.tools.rating_alert.get_reply_history", return_value=_STABLE_HISTORY):
            with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 0

    def test_exits_1_when_decline_detected(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert", "--dry-run"])
        with _freeze_main_date():
            with patch(
                "meo.tools.rating_alert.get_reply_history",
                return_value=_DECLINING_HISTORY,
            ):
                with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
                    with pytest.raises(SystemExit) as exc:
                        main()
        assert exc.value.code == 1

    def test_dry_run_does_not_send_slack(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert", "--dry-run"])
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        with patch(
            "meo.tools.rating_alert.get_reply_history",
            return_value=_DECLINING_HISTORY,
        ):
            with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
                with patch("meo.tools.rating_alert.requests.post") as mock_post:
                    with pytest.raises(SystemExit):
                        main()
        mock_post.assert_not_called()

    def test_live_sends_slack_on_decline(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert"])
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with _freeze_main_date():
            with patch(
                "meo.tools.rating_alert.get_reply_history",
                return_value=_DECLINING_HISTORY,
            ):
                with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
                    with patch(
                        "meo.tools.rating_alert.requests.post", return_value=mock_resp
                    ) as mock_post:
                        with pytest.raises(SystemExit):
                            main()
        mock_post.assert_called_once()

    def test_unknown_store_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert", "--store", "no_such_store"])
        with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_invalid_window_days_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert", "--window-days", "0"])
        with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_invalid_min_drop_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert", "--min-drop", "-0.1"])
        with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_invalid_min_replies_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-rating-alert", "--min-replies", "0"])
        with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_single_store_filter(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv",
            ["meo-rating-alert", "--dry-run", "--store", "the_body_kyoto"],
        )
        with _freeze_main_date():
            with patch(
                "meo.tools.rating_alert.get_reply_history",
                return_value=_DECLINING_HISTORY,
            ):
                with patch("meo.tools.rating_alert.cfg.store_list", return_value=_STORES):
                    with pytest.raises(SystemExit) as exc:
                        main()
        assert exc.value.code == 1  # decline detected for kyoto
