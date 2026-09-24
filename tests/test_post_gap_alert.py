"""Tests for meo-post-gap-alert."""

from __future__ import annotations

import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from meo.tools.post_gap_alert import (
    _DEFAULT_GAP_MULTIPLIER,
    _default_max_gap,
    _format_alert,
    _send_alert,
    compute_gaps,
    main,
    run_post_gap_alert,
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

_TODAY = date(2026, 9, 24)

# ---------------------------------------------------------------------------
# _default_max_gap
# ---------------------------------------------------------------------------

class TestDefaultMaxGap:
    def test_uses_cadence_multiplier(self):
        with patch("meo.tools.post_gap_alert.cfg.content", return_value={"defaults": {"post_cadence_days": 2}}):
            assert _default_max_gap() == 2 * _DEFAULT_GAP_MULTIPLIER

    def test_defaults_to_1_day_cadence_when_missing(self):
        with patch("meo.tools.post_gap_alert.cfg.content", return_value={"defaults": {}}):
            assert _default_max_gap() == 1 * _DEFAULT_GAP_MULTIPLIER

    def test_min_one_day(self):
        with patch("meo.tools.post_gap_alert.cfg.content", return_value={"defaults": {"post_cadence_days": 0}}):
            result = _default_max_gap()
            assert result >= 1

    def test_handles_config_error(self):
        with patch("meo.tools.post_gap_alert.cfg.content", side_effect=Exception("cfg error")):
            # should fall back gracefully
            result = _default_max_gap()
            assert result >= 1


# ---------------------------------------------------------------------------
# compute_gaps
# ---------------------------------------------------------------------------

class TestComputeGaps:
    def _patch_last_post(self, dates_by_key: dict):
        def _get(key):
            return dates_by_key.get(key)
        return patch("meo.tools.post_gap_alert.get_last_post_date", side_effect=_get)

    def test_recent_post_included(self):
        dates = {
            "the_body_osaka_shinsaibashi": "2026-09-23",
            "the_body_kyoto": "2026-09-20",
            "mybear_studio_kyoto": "2026-09-10",
        }
        with self._patch_last_post(dates):
            gaps = compute_gaps(_STORES, today=_TODAY)
        assert len(gaps) == 3
        shinsaibashi = next(g for g in gaps if g["store_key"] == "the_body_osaka_shinsaibashi")
        assert shinsaibashi["days_since"] == 1
        kyoto = next(g for g in gaps if g["store_key"] == "the_body_kyoto")
        assert kyoto["days_since"] == 4
        mybear = next(g for g in gaps if g["store_key"] == "mybear_studio_kyoto")
        assert mybear["days_since"] == 14

    def test_never_posted_excluded_by_default(self):
        with self._patch_last_post({}):
            gaps = compute_gaps(_STORES, today=_TODAY)
        assert gaps == []

    def test_never_posted_included_when_flag_set(self):
        with self._patch_last_post({}):
            gaps = compute_gaps(_STORES, today=_TODAY, include_never_posted=True)
        assert len(gaps) == 3
        for g in gaps:
            assert g["last_post_date"] is None
            assert g["days_since"] is None

    def test_invalid_date_string_treated_as_never_posted(self):
        dates = {"the_body_kyoto": "not-a-date"}
        with self._patch_last_post(dates):
            gaps = compute_gaps([_STORES[1]], today=_TODAY)
        # invalid date is excluded (treated as never-posted, default exclude)
        assert gaps == []

    def test_invalid_date_included_when_flag_set(self):
        dates = {"the_body_kyoto": "not-a-date"}
        with self._patch_last_post(dates):
            gaps = compute_gaps([_STORES[1]], today=_TODAY, include_never_posted=True)
        assert len(gaps) == 1
        assert gaps[0]["last_post_date"] is None

    def test_same_day_post_is_zero_days(self):
        dates = {"the_body_kyoto": "2026-09-24"}
        with self._patch_last_post(dates):
            gaps = compute_gaps([_STORES[1]], today=_TODAY)
        assert gaps[0]["days_since"] == 0

    def test_uses_jst_today_when_not_provided(self):
        dates = {"the_body_kyoto": "2026-09-23"}
        with self._patch_last_post(dates):
            # no today= provided; should not raise
            gaps = compute_gaps([_STORES[1]])
        assert gaps[0]["days_since"] is not None

    def test_last_post_date_in_result(self):
        dates = {"the_body_kyoto": "2026-09-20"}
        with self._patch_last_post(dates):
            gaps = compute_gaps([_STORES[1]], today=_TODAY)
        assert gaps[0]["last_post_date"] == "2026-09-20"


# ---------------------------------------------------------------------------
# run_post_gap_alert
# ---------------------------------------------------------------------------

class TestRunPostGapAlert:
    def _patch_last_post(self, dates_by_key: dict):
        def _get(key):
            return dates_by_key.get(key)
        return patch("meo.tools.post_gap_alert.get_last_post_date", side_effect=_get)

    def test_no_alert_when_all_recent(self):
        dates = {
            "the_body_osaka_shinsaibashi": "2026-09-23",
            "the_body_kyoto": "2026-09-23",
            "mybear_studio_kyoto": "2026-09-23",
        }
        with self._patch_last_post(dates):
            alerts = run_post_gap_alert(_STORES, max_gap_days=3, today=_TODAY)
        assert alerts == []

    def test_alert_when_gap_exceeds_threshold(self):
        dates = {
            "the_body_osaka_shinsaibashi": "2026-09-23",
            "the_body_kyoto": "2026-09-20",  # 4 days ago
            "mybear_studio_kyoto": "2026-09-23",
        }
        with self._patch_last_post(dates):
            alerts = run_post_gap_alert(_STORES, max_gap_days=3, today=_TODAY)
        assert len(alerts) == 1
        assert alerts[0]["store_key"] == "the_body_kyoto"
        assert alerts[0]["days_since"] == 4

    def test_exact_threshold_triggers(self):
        dates = {"the_body_kyoto": "2026-09-21"}  # exactly 3 days ago
        with self._patch_last_post(dates):
            alerts = run_post_gap_alert([_STORES[1]], max_gap_days=3, today=_TODAY)
        assert len(alerts) == 1

    def test_one_below_threshold_no_alert(self):
        dates = {"the_body_kyoto": "2026-09-22"}  # 2 days ago
        with self._patch_last_post(dates):
            alerts = run_post_gap_alert([_STORES[1]], max_gap_days=3, today=_TODAY)
        assert alerts == []

    def test_never_posted_excluded_by_default(self):
        with self._patch_last_post({}):
            alerts = run_post_gap_alert(_STORES, max_gap_days=3, today=_TODAY)
        assert alerts == []

    def test_never_posted_included_when_flag(self):
        with self._patch_last_post({}):
            alerts = run_post_gap_alert(
                _STORES, max_gap_days=3, today=_TODAY, include_never_posted=True
            )
        assert len(alerts) == 3

    def test_multiple_stores_alerted(self):
        dates = {
            "the_body_osaka_shinsaibashi": "2026-09-10",
            "the_body_kyoto": "2026-09-10",
            "mybear_studio_kyoto": "2026-09-23",
        }
        with self._patch_last_post(dates):
            alerts = run_post_gap_alert(_STORES, max_gap_days=3, today=_TODAY)
        assert len(alerts) == 2
        keys = {a["store_key"] for a in alerts}
        assert keys == {"the_body_osaka_shinsaibashi", "the_body_kyoto"}

    def test_uses_default_gap_when_none(self):
        dates = {}
        with self._patch_last_post(dates), \
             patch("meo.tools.post_gap_alert.cfg.content", return_value={"defaults": {"post_cadence_days": 1}}):
            alerts = run_post_gap_alert(_STORES, max_gap_days=None, today=_TODAY)
        # no stores have posted → excluded by default (include_never_posted=False)
        assert alerts == []

    def test_store_isolation(self):
        dates = {
            "the_body_osaka_shinsaibashi": "2026-09-10",
            "the_body_kyoto": "2026-09-23",
            "mybear_studio_kyoto": "2026-09-23",
        }
        with self._patch_last_post(dates):
            alerts = run_post_gap_alert(_STORES, max_gap_days=3, today=_TODAY)
        assert len(alerts) == 1
        assert alerts[0]["store_key"] == "the_body_osaka_shinsaibashi"


# ---------------------------------------------------------------------------
# _format_alert
# ---------------------------------------------------------------------------

class TestFormatAlert:
    def _make_alert(self, key, name, last_date, days):
        return {"store_key": key, "store_name": name, "last_post_date": last_date, "days_since": days}

    def test_contains_store_name(self):
        a = self._make_alert("the_body_kyoto", "THE BODY 京都店", "2026-09-20", 4)
        msg = _format_alert([a], max_gap_days=3, now="2026-09-24 10:00 JST")
        assert "THE BODY 京都店" in msg

    def test_contains_days_since(self):
        a = self._make_alert("the_body_kyoto", "THE BODY 京都店", "2026-09-20", 4)
        msg = _format_alert([a], max_gap_days=3, now="2026-09-24 10:00 JST")
        assert "4日" in msg

    def test_contains_last_post_date(self):
        a = self._make_alert("the_body_kyoto", "THE BODY 京都店", "2026-09-20", 4)
        msg = _format_alert([a], max_gap_days=3, now="2026-09-24 10:00 JST")
        assert "2026-09-20" in msg

    def test_never_posted_label(self):
        a = self._make_alert("the_body_kyoto", "THE BODY 京都店", None, None)
        msg = _format_alert([a], max_gap_days=3, now="2026-09-24 10:00 JST")
        assert "未投稿" in msg or "なし" in msg

    def test_count_in_header(self):
        alerts = [
            self._make_alert("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", "2026-09-10", 14),
            self._make_alert("mybear_studio_kyoto", "MYBEAR STUDIO 京都店", "2026-09-01", 23),
        ]
        msg = _format_alert(alerts, max_gap_days=3, now="2026-09-24 10:00 JST")
        assert "2店舗" in msg

    def test_uses_now_string(self):
        a = self._make_alert("the_body_kyoto", "THE BODY 京都店", "2026-09-20", 4)
        msg = _format_alert([a], max_gap_days=3, now="2026-09-24 10:00 JST")
        assert "2026-09-24 10:00 JST" in msg

    def test_now_defaults_to_jst_when_not_provided(self):
        a = self._make_alert("the_body_kyoto", "THE BODY 京都店", "2026-09-20", 4)
        msg = _format_alert([a], max_gap_days=3)
        assert "JST" in msg


# ---------------------------------------------------------------------------
# _send_alert
# ---------------------------------------------------------------------------

class TestSendAlert:
    def test_returns_false_when_no_url(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert _send_alert("test message") is False

    def test_sends_post_to_slack(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch("meo.tools.post_gap_alert.requests.post", return_value=mock_resp) as mock_post:
            result = _send_alert("alert text")
        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["text"] == "alert text"

    def test_handles_http_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("meo.tools.post_gap_alert.requests.post", return_value=mock_resp):
            assert _send_alert("msg") is False

    def test_handles_connection_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        with patch("meo.tools.post_gap_alert.requests.post", side_effect=Exception("conn error")):
            assert _send_alert("msg") is False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_all(self, dates_by_key: dict, monkeypatch):
        def _get(key):
            return dates_by_key.get(key)
        monkeypatch.setattr("meo.tools.post_gap_alert.get_last_post_date", _get)
        monkeypatch.setattr(
            "meo.tools.post_gap_alert.cfg.store_list",
            lambda: list(_STORES),
        )
        monkeypatch.setattr(
            "meo.tools.post_gap_alert.cfg.content",
            lambda: {"defaults": {"post_cadence_days": 1}},
        )

    def test_exits_0_when_no_gaps(self, monkeypatch, capsys):
        dates = {s["key"]: "2026-09-23" for s in _STORES}
        self._patch_all(dates, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["meo-post-gap-alert", "--max-gap-days", "3"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    def test_exits_1_when_gap_detected(self, monkeypatch, capsys):
        dates = {
            "the_body_osaka_shinsaibashi": "2026-09-23",
            "the_body_kyoto": "2026-09-10",
            "mybear_studio_kyoto": "2026-09-23",
        }
        self._patch_all(dates, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["meo-post-gap-alert", "--max-gap-days", "3"])
        with patch("meo.tools.post_gap_alert._send_alert") as mock_send:
            mock_send.return_value = True
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_dry_run_does_not_send(self, monkeypatch, capsys):
        dates = {"the_body_kyoto": "2026-09-10"}
        self._patch_all(dates, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["meo-post-gap-alert", "--max-gap-days", "3", "--dry-run"])
        with patch("meo.tools.post_gap_alert._send_alert") as mock_send:
            with pytest.raises(SystemExit):
                main()
        mock_send.assert_not_called()

    def test_live_run_sends_alert(self, monkeypatch, capsys):
        dates = {"the_body_kyoto": "2026-09-10"}
        self._patch_all(dates, monkeypatch)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        monkeypatch.setattr(sys, "argv", ["meo-post-gap-alert", "--max-gap-days", "3"])
        with patch("meo.tools.post_gap_alert._send_alert", return_value=True) as mock_send:
            with pytest.raises(SystemExit):
                main()
        mock_send.assert_called_once()

    def test_store_filter(self, monkeypatch, capsys):
        dates = {
            "the_body_osaka_shinsaibashi": "2026-09-10",
            "the_body_kyoto": "2026-09-23",
            "mybear_studio_kyoto": "2026-09-10",
        }
        self._patch_all(dates, monkeypatch)
        monkeypatch.setattr(
            sys, "argv",
            ["meo-post-gap-alert", "--max-gap-days", "3", "--store", "the_body_kyoto"],
        )
        with pytest.raises(SystemExit) as exc:
            main()
        # the_body_kyoto posted recently → no alert
        assert exc.value.code == 0

    def test_unknown_store_exits_1(self, monkeypatch, capsys):
        self._patch_all({}, monkeypatch)
        monkeypatch.setattr(
            sys, "argv",
            ["meo-post-gap-alert", "--store", "nonexistent_store"],
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_invalid_max_gap_exits_1(self, monkeypatch, capsys):
        self._patch_all({}, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["meo-post-gap-alert", "--max-gap-days", "0"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_include_never_posted_flag(self, monkeypatch, capsys):
        # No stores have posted → normally no alerts, but with --include-never-posted → alert
        self._patch_all({}, monkeypatch)
        monkeypatch.setattr(
            sys, "argv",
            ["meo-post-gap-alert", "--max-gap-days", "3", "--include-never-posted"],
        )
        with patch("meo.tools.post_gap_alert._send_alert", return_value=True):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_default_gap_used_when_not_specified(self, monkeypatch, capsys):
        dates = {s["key"]: "2026-09-23" for s in _STORES}
        self._patch_all(dates, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["meo-post-gap-alert"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
